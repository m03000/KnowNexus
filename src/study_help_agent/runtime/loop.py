"""通用 Loop Agent 主循环。

本文件固定的是 decide、act、observe、validate 的运行协议。
模型每轮决策选择下一步，Runtime 负责预算、重复动作检测、工具权限和完成验收。
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Callable
from uuid import uuid4

from study_help_agent.runtime.artifacts import ArtifactStore
from study_help_agent.runtime.budgets import BudgetPolicy
from study_help_agent.runtime.completion import CompletionPolicy
from study_help_agent.runtime.context import AgentLoopContextBuilder
from study_help_agent.runtime.decision import DecisionProvider
from study_help_agent.runtime.state import (
    AgentRunState,
    FinishAction,
    LoadSkillAction,
    LoopRunStatus,
    Observation,
    ObservationStatus,
    RequestUserInputAction,
    ToolCallAction,
)
from study_help_agent.runtime.tools import ToolExecutor, ToolRegistry
from study_help_agent.runtime.skills import SkillRegistry
from study_help_agent.runtime.streaming import StreamEvent
from study_help_agent.runtime.cancellation import CancellationToken, AgentCancelledError
from study_help_agent.observability import get_observability_recorder

EventSink = Callable[[StreamEvent], None]


class AgentLoop:
    """协调决策器、工具、状态、预算与完成策略的可复用运行引擎。"""

    def __init__(
        self,
        *,
        decision_provider: DecisionProvider,                    # 动作决策者
        tool_registry: ToolRegistry,                            # 工具注册表
        tool_executor: ToolExecutor,                            # 工具执行者
        artifact_store: ArtifactStore,                          # 中间产出的最小内容
        budget_policy: BudgetPolicy,                            # 预算协议
        completion_policy: CompletionPolicy,                    # 验收决定者
        context_builder: AgentLoopContextBuilder | None = None, # 上下文组装
        skill_registry: SkillRegistry | None = None,            # skill注册表
        event_sink: EventSink | None = None,                    # 可选公开过程事件出口
        cancellation_token: CancellationToken | None = None,
        complete_on_task_ready: bool = False,
    ) -> None:
        """注入所有可替换组件，主循环本身不依赖具体业务和 LLM 厂商。"""

        self._decision_provider = decision_provider
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._artifact_store = artifact_store
        self._budget_policy = budget_policy
        self._completion_policy = completion_policy
        self._context_builder = context_builder or AgentLoopContextBuilder()
        self._skill_registry = skill_registry
        self._event_sink = event_sink
        self._cancellation_token = cancellation_token or CancellationToken()
        self._complete_on_task_ready = complete_on_task_ready

    def run(self, *, goal: str, run_id: str | None = None) -> AgentRunState:
        """从用户目标开始持续决策，直到完成、受阻或预算耗尽。"""
        # 获取目标
        normalized_goal = goal.strip()
        if not normalized_goal:
            raise ValueError("Agent goal cannot be empty")
        # 补充初始状态信息
        state = AgentRunState(
            run_id=run_id or f"agent_run_{uuid4().hex}",
            goal=normalized_goal,
        )
        # 推送事件
        self._emit("agent_start", state, {"message": "Agent 已开始处理请求"})
        previous_signature: str | None = None

        # loop循环执行
        while state.status == LoopRunStatus.RUNNING:
            if self._cancellation_token.cancelled:
                state.status = LoopRunStatus.CANCELLED
                break
            # 预算耗尽，结束循环
            if not state.task_completed and not self._budget_policy.can_decide(state):
                state.status = LoopRunStatus.BUDGET_EXHAUSTED
                break
            # 上下文组装
            context = self._context_builder.build(
                state=state,
                tools=self._tool_registry,
                artifacts=self._artifact_store,
                budget=self._budget_policy,
                skills=self._skill_registry,
            )
            # 获取此轮决定
            try:
                decision = self._decision_provider.decide(context)
                self._cancellation_token.raise_if_cancelled()
            except AgentCancelledError:
                state.status = LoopRunStatus.CANCELLED
                break
            except Exception:
                if state.task_completed and state.finalization_fallback_answer:
                    self._finish_with_fallback(state, "最终回答整理失败，已返回工具结果")
                    break
                raise
            # 记录决定
            state.record_decision(decision)
            self._emit(
                "thought_summary",
                state,
                {"message": decision.reasoning_summary, "iteration": state.iteration},
            )
            # 行为标识获取
            signature = self._action_signature(decision.action)
            if signature == previous_signature:
                state.repeated_action_count += 1
            else:
                state.repeated_action_count = 0
            previous_signature = signature

            # 重复动作超过限制
            if self._budget_policy.repeated_action_exceeded(state):
                state.record_observation(
                    self._runtime_observation(
                        state=state,
                        status=ObservationStatus.FAILED,
                        summary=(
                            "Repeated action limit reached. Choose a different strategy "
                            "or explain why the goal cannot be completed."
                        ),
                    )
                )
                continue
            # 根据行为标识执行：加载skill、调用工具、询问用户信息、结束行动
            action = decision.action
            if state.task_completed and not isinstance(action, FinishAction):
                self._finish_with_fallback(
                    state,
                    "收尾阶段收到非 finish 动作，已阻止继续执行并返回工具结果",
                )
                break
            if isinstance(action, LoadSkillAction):
                # 加载skill
                self._emit("skill_start", state, {"skill_name": action.skill_name})
                # 获取skill内容并记录到observation
                state.record_observation(self._load_skill(state=state, action=action))
                self._emit("skill_end", state, {"skill_name": action.skill_name})
                continue
            if isinstance(action, ToolCallAction):
                # 预算耗尽，不再调用工具
                if not self._budget_policy.can_call_tool(state):
                    state.status = LoopRunStatus.BUDGET_EXHAUSTED
                    break
                self._emit(
                    "tool_start", state,
                    {"tool_name": action.tool_name, "purpose": action.purpose},
                )
                # 调用工具并记录结果
                try:
                    observation = self._tool_executor.execute(
                        run_id=state.run_id,
                        action_index=state.iteration,
                        tool_name=action.tool_name,
                        arguments=action.arguments,
                    )
                    self._cancellation_token.raise_if_cancelled()
                except AgentCancelledError:
                    state.status = LoopRunStatus.CANCELLED
                    break
                # 记录工具调用次数并记录结果
                state.tool_calls += 1
                state.record_observation(observation)
                self._emit(
                    "tool_end",
                    state,
                    {
                        "tool_name": action.tool_name,
                        "status": observation.status.value,
                        "summary": observation.summary,
                    },
                )
                if (
                    observation.payload.get("task_completed") is True
                    or observation.payload.get("task_terminal") is True
                ):
                    state.task_completed = True
                    state.finalization_fallback_answer = str(
                        observation.payload.get("final_answer_hint")
                        or observation.summary
                    ).strip()
                    self._emit(
                        "task_ready",
                        state,
                        {
                            "message": (
                                "全部产物已经完成"
                                if self._complete_on_task_ready
                                else "全部产物已经完成，正在整理最终回答"
                            )
                        },
                    )
                if (
                    observation.payload.get("task_completed") is True
                    and self._complete_on_task_ready
                ):
                    self._finish_with_fallback(
                        state,
                        "业务工具已明确完成全部产物，跳过 Agent 内部回答阶段",
                    )
                    break
                if (
                    observation.status == ObservationStatus.FAILED
                    and observation.payload.get("terminal") is True
                ):
                    state.status = LoopRunStatus.BLOCKED
                    state.blocked_question = (
                        "当前操作被安全策略拒绝，已停止自动重试。"
                        f"{observation.summary}"
                    )
                    self._emit(
                        "agent_blocked",
                        state,
                        {
                            "message": state.blocked_question,
                            "tool_name": action.tool_name,
                        },
                    )
                    break
                continue

            # 需要用户输入，结束循环
            if isinstance(action, RequestUserInputAction):
                state.status = LoopRunStatus.BLOCKED
                # 询问内容
                state.blocked_question = action.question
                state.record_observation(
                    self._runtime_observation(
                        state=state,
                        status=ObservationStatus.PARTIAL,
                        summary=f"User input required: {action.reason}",
                        payload={"question": action.question},
                    )
                )
                break
            # 兜底检查
            assert isinstance(action, FinishAction)
            # 结果验收
            validation = self._completion_policy.validate(
                state=state,
                action=action,
                artifact_store=self._artifact_store,
            )
            # 验收通过，结束循环
            if validation.accepted:
                state.status = LoopRunStatus.COMPLETED
                state.final_answer = action.answer.strip()
                break
            # 记录 observation
            state.record_observation(
                self._runtime_observation(
                    state=state,
                    status=ObservationStatus.FAILED,
                    summary="Finish request rejected by completion policy",
                    payload={"issues": list(validation.issues)},
                )
            )
            self._emit(
                "completion_rejected",
                state,
                {"message": "完成验收未通过", "issues": list(validation.issues)},
            )
            if state.task_completed and state.finalization_fallback_answer:
                self._finish_with_fallback(state, "最终回答验收未通过，已返回工具结果")
                break

        self._emit(
            "agent_end",
            state,
            {"status": state.status.value, "iterations": state.iteration, "tool_calls": state.tool_calls},
        )
        if state.status == LoopRunStatus.CANCELLED:
            self._emit(
                "agent_cancelled", state,
                {"message": self._cancellation_token.reason},
            )
        return state

    def _finish_with_fallback(self, state: AgentRunState, reason: str) -> None:
        """收尾决策异常时使用已完成工具的结果结束，禁止重新进入业务循环。"""

        state.status = LoopRunStatus.COMPLETED
        state.final_answer = state.finalization_fallback_answer.strip()
        self._emit(
            "finalization_fallback",
            state,
            {"message": reason},
        )

    def _emit(self, event: str, state: AgentRunState, data: dict) -> None:
        """尽力发送可公开事件；观察功能故障不能打断 Agent 主任务。"""

        try:
            get_observability_recorder().record(
                event,
                data={**data, "agent_run_id": state.run_id},
                status=str(data.get("status") or "") or None,
            )
        except Exception:
            pass
        if self._event_sink is None:
            return
        try:
            self._event_sink(StreamEvent(event=event, run_id=state.run_id, data=data))
        except Exception:
            return

    def _load_skill(self, *, state: AgentRunState, action: LoadSkillAction) -> Observation:
        """校验并记录 Skill 加载，让下一轮上下文获得完整 Skill 指令。"""

        if self._skill_registry is None:
            return self._runtime_observation(state=state, status=ObservationStatus.FAILED, summary="No SkillRegistry is configured.")
        try:
            # 获取skill
            skill = self._skill_registry.get(action.skill_name)
        except KeyError as error:
            return self._runtime_observation(state=state, status=ObservationStatus.FAILED, summary=str(error))
        if skill.name not in state.loaded_skill_names:
            state.loaded_skill_names.append(skill.name)
        return self._runtime_observation(
            state=state,
            status=ObservationStatus.SUCCESS,
            summary=f"Skill loaded: {skill.name}",
            payload={"skill_name": skill.name, "allowed_tools": list(skill.allowed_tools)},
        )

    @staticmethod
    def _action_signature(action: object) -> str:
        """为动作生成比较签名，用于发现无进展的连续重复调用。"""

        if isinstance(action, ToolCallAction):
            return json.dumps(
                {"tool": action.tool_name, "arguments": dict(action.arguments)},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        return repr(action)

    @staticmethod
    def _runtime_observation(
        *,
        state: AgentRunState,
        status: ObservationStatus,
        summary: str,
        payload: dict | None = None,
    ) -> Observation:
        """把预算、暂停或验收事件包装成与工具反馈相同的 Observation。"""

        digest = sha256(
            f"{state.run_id}|{state.iteration}|{summary}".encode("utf-8")
        ).hexdigest()[:20]
        return Observation(
            observation_id=f"runtime_observation_{digest}",
            action_index=state.iteration,
            status=status,
            summary=summary,
            payload=payload or {},
        )

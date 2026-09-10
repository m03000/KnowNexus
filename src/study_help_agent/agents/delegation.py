"""把专业 Sub-Agent Loop 注册为主 Agent 可调用的委派工具。

委派工具为 Sub-Agent 创建独立上下文和预算，共享的只有 Artifact Store。Sub-Agent 的
详细轨迹保存为 Artifact，主 Agent 只接收状态、结论和产物引用。
"""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from study_help_agent.agents.factory import AgentLoopFactory
from study_help_agent.runtime.state import LoopRunStatus
from study_help_agent.runtime.streaming import StreamEvent
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult


class SubAgentDelegationTools:
    """提供代码、学习和 RAG 检索的专业 Loop Agent 委派工具。"""

    def __init__(self, *, factory: AgentLoopFactory) -> None:
        """保存通用 Loop 工厂。"""

        self._factory = factory

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回主 Agent 可使用的三个专业委派工具。"""

        return (
            self._definition("delegate_code_agent", "code", "委派本地 Python 项目或单文件解析任务给 Code Intelligence Sub-Agent。"),
            self._definition("delegate_note_agent", "note", "委派学习笔记和教学内容目标给 Note Sub-Agent。"),
            self._definition("delegate_rag_agent", "rag", "委派个人知识库证据检索目标给 RAG Retrieval Sub-Agent。"),
        )

    def _definition(self, name: str, profile_key: str, description: str) -> ToolDefinition:
        """创建绑定到指定 Profile 的委派工具定义。"""

        return ToolDefinition(
            name=name,
            description=description,
            parameters={"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]},
            handler=lambda arguments, context: self.delegate(
                arguments, context, profile_key=profile_key
            ),
        )

    def delegate(
        self,
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
        *,
        profile_key: str,
    ) -> ToolResult:
        """运行独立 Sub-Agent Loop，并把完整运行状态存入共享 Artifact Store。"""

        goal = str(arguments["goal"]).strip()
        if not goal:
            raise ValueError("Sub-agent goal cannot be empty")
        def publish_child(event: StreamEvent) -> None:
            if context.event_sink is None:
                return
            context.event_sink(StreamEvent(
                event=event.event,
                run_id=event.run_id,
                agent=profile_key,
                timestamp=event.timestamp,
                data={**dict(event.data), "parent_run_id": context.run_id},
            ))

        if context.event_sink is not None:
            context.event_sink(StreamEvent(
                event="sub_agent_start",
                run_id=context.run_id,
                agent=profile_key,
                data={"message": f"{profile_key} Sub-Agent 开始执行", "parent_run_id": context.run_id},
            ))
        state = self._factory.run(
            profile_key=profile_key,
            goal=goal,
            run_id=f"{context.run_id}:{profile_key}:{uuid4().hex[:12]}",
            event_sink=publish_child if context.event_sink is not None else None,
            cancellation_token=context.cancellation_token,
        )
        if context.event_sink is not None:
            context.event_sink(StreamEvent(
                event="sub_agent_end",
                run_id=state.run_id,
                agent=profile_key,
                data={
                    "message": f"{profile_key} Sub-Agent 执行结束",
                    "status": state.status.value,
                    "iterations": state.iteration,
                    "tool_calls": state.tool_calls,
                    "parent_run_id": context.run_id,
                },
            ))
        artifact = context.artifact_store.put(
            artifact_type="sub_agent_run",
            name=f"{profile_key}-{state.run_id}",
            summary=f"{profile_key} sub-agent finished with {state.status.value}",
            content=state,
        )
        completed = state.status == LoopRunStatus.COMPLETED
        return ToolResult(
            summary=(
                f"{profile_key} Sub-Agent 已完成。"
                if completed
                else f"{profile_key} Sub-Agent 未完成：{state.status.value}。"
            ),
            payload={
                "profile_key": profile_key,
                "status": state.status.value,
                "answer": state.final_answer or "",
                "question": state.blocked_question or "",
                "run_artifact_id": artifact.artifact_id,
                "produced_artifact_ids": list(state.artifact_ids),
            },
            artifact_ids=(artifact.artifact_id, *tuple(state.artifact_ids)),
            warnings=() if completed else ("Sub-Agent did not reach completed status",),
            partial=not completed,
        )

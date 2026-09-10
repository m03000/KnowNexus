"""根据 AgentProfile 创建隔离能力的通用 Loop Agent。

所有 Agent 共享同一种运行协议，但获得不同的 ToolRegistry、SkillRegistry、系统指令和
预算。这样主 Agent 与 Sub-Agent 都是 Loop，同时不会得到超出职责的能力。
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from study_help_agent.runtime.artifacts import ArtifactStore
from study_help_agent.runtime.budgets import BudgetPolicy
from study_help_agent.runtime.completion import DefaultCompletionPolicy
from study_help_agent.runtime.decision import LangChainDecisionProvider
from study_help_agent.runtime.loop import AgentLoop
from study_help_agent.runtime.state import AgentRunState
from study_help_agent.runtime.skills import SkillRegistry
from study_help_agent.runtime.loop import EventSink
from study_help_agent.runtime.cancellation import CancellationToken
from study_help_agent.runtime.tools import (
    ToolExecutor,
    ToolRegistry,
    ToolResultObserver,
)
from study_help_agent.agents.registry import AgentProfile, AgentProfileRegistry
from study_help_agent.observability import trace_scope


class AgentLoopFactory:
    """为任意 Profile 构造并运行具有最小权限视图的 AgentLoop。"""

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        tools: ToolRegistry,
        skills: SkillRegistry,
        artifacts: ArtifactStore,
        profiles: AgentProfileRegistry,
        result_observers: tuple[ToolResultObserver, ...] = (),
    ) -> None:
        """保存共享基础设施；具体权限在每次创建 Loop 时裁剪。"""

        self._llm = llm
        self._tools = tools
        self._skills = skills
        self._artifacts = artifacts
        self._profiles = profiles
        self._result_observers = result_observers

    def create(
        self, profile: AgentProfile, *, event_sink: EventSink | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AgentLoop:
        """根据 Profile 构造一次全新的、状态隔离的 Loop。"""

        tools = self._tools.select(profile.tool_names)
        skills = self._skills.select(profile.skill_names)
        return AgentLoop(
            decision_provider=LangChainDecisionProvider(
                llm=self._llm,
                system_instructions=profile.system_instructions,
            ),
            tool_registry=tools,
            tool_executor=ToolExecutor(
                registry=tools,
                artifact_store=self._artifacts,
                result_observers=self._result_observers,
                event_sink=event_sink,
                cancellation_token=cancellation_token,
            ),
            artifact_store=self._artifacts,
            budget_policy=BudgetPolicy(profile.budget),
            completion_policy=DefaultCompletionPolicy(
                minimum_successful_actions=profile.minimum_successful_actions,
                required_artifact_types=profile.required_artifact_types,
                required_if_keywords=profile.required_if_keywords,
            ),
            skill_registry=skills,
            event_sink=event_sink,
            cancellation_token=cancellation_token,
            complete_on_task_ready=profile.complete_on_task_ready,
        )

    def run(
        self,
        *,
        profile_key: str,
        goal: str,
        run_id: str | None = None,
        event_sink: EventSink | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AgentRunState:
        """读取 Profile 并运行对应 Loop。"""

        profile = self._profiles.get(profile_key)
        with trace_scope(agent=profile_key, stage="agent_loop"):
            return self.create(
                profile, event_sink=event_sink, cancellation_token=cancellation_token,
            ).run(goal=goal, run_id=run_id)

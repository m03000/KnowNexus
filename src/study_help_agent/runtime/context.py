"""Loop 每一轮的上下文构建器。

它只选取最近观察、Artifact 引用、剩余预算和可用工具，不直接传入完整历史与大文件，
从而控制 Token 规模并让 LLM 聚焦当前状态。
"""

from study_help_agent.runtime.artifacts import ArtifactStore
from study_help_agent.runtime.budgets import BudgetPolicy
from study_help_agent.runtime.state import AgentLoopContext, AgentRunState
from study_help_agent.runtime.tools import ToolRegistry
from study_help_agent.runtime.skills import SkillRegistry


class AgentLoopContextBuilder:
    """根据可变运行状态构建只读的单轮决策上下文。"""

    def __init__(self, *, recent_observation_limit: int = 8) -> None:
        """设置每轮最多携带多少条最近观察。"""

        if recent_observation_limit < 1:
            raise ValueError("recent_observation_limit must be positive")
        self._recent_observation_limit = recent_observation_limit

    def build(
        self,
        *,
        state: AgentRunState,
        tools: ToolRegistry,
        artifacts: ArtifactStore,
        budget: BudgetPolicy,
        skills: SkillRegistry | None = None,
    ) -> AgentLoopContext:
        """把内部状态裁剪成决策器需要的最小上下文快照。"""

        return AgentLoopContext(
            run_id=state.run_id,
            goal=state.goal,
            iteration=state.iteration,
            recent_observations=tuple(
                state.observations[-self._recent_observation_limit :]
            ),
            artifacts=artifacts.references(tuple(state.artifact_ids)),
            available_tools=() if state.task_completed else tools.schemas(),
            remaining_iterations=max(
                0, budget.budget.max_iterations - state.iteration
            ),
            remaining_tool_calls=max(
                0, budget.budget.max_tool_calls - state.tool_calls
            ),
            available_skills=(
                () if state.task_completed
                else skills.summaries() if skills is not None else ()
            ),
            loaded_skills=(
                skills.loaded(tuple(state.loaded_skill_names))
                if skills is not None
                else ()
            ),
            finalizing=state.task_completed,
            finalization_hint=state.finalization_fallback_answer,
        )

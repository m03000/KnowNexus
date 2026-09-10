"""Loop Agent 的资源预算与停止边界。

LLM 可以自主决定业务步骤，但不能无限循环。
本文件把迭代次数、工具调用次数和重复动作次数定义成程序化边界，确保运行成本和失控风险可预测。
"""

from dataclasses import dataclass

from study_help_agent.runtime.state import AgentRunState


@dataclass(frozen=True, slots=True)
class LoopBudget:
    """声明一次 Loop 允许消耗的最大资源。"""

    max_iterations: int = 20
    max_tool_calls: int = 15
    max_repeated_actions: int = 2

    def __post_init__(self) -> None:
        """拒绝无法运行的零值或负数预算。"""

        if min(
            self.max_iterations,
            self.max_tool_calls,
            self.max_repeated_actions,
        ) < 1:
            raise ValueError("Loop budget values must be positive")


class BudgetPolicy:
    """根据 AgentRunState 判断是否还能继续决策或调用工具。"""

    def __init__(self, budget: LoopBudget | None = None) -> None:
        """使用调用方预算，未提供时采用安全默认值。"""

        self.budget = budget or LoopBudget()

    def can_decide(self, state: AgentRunState) -> bool:
        """判断是否还剩至少一次 LLM 决策机会。"""

        return state.iteration < self.budget.max_iterations

    def can_call_tool(self, state: AgentRunState) -> bool:
        """判断是否还剩至少一次工具调用机会。"""

        return state.tool_calls < self.budget.max_tool_calls

    def repeated_action_exceeded(self, state: AgentRunState) -> bool:
        """判断 Agent 是否连续重复相同动作，可能已经失去进展。"""

        return state.repeated_action_count >= self.budget.max_repeated_actions

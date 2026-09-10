"""定义工具成功后的通用观察者协议，使 Runtime 不依赖具体业务。"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from study_help_agent.runtime.tools.core import ToolExecutionContext, ToolResult


@dataclass(frozen=True, slots=True)
class ToolResultObserverOutput:
    """观察者可追加轻量状态，但不能替换原业务结果。"""

    payload: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class ToolResultObserver(Protocol):
    """在工具 handler 成功返回后接收通知的扩展点。"""

    def after_success(
        self,
        *,
        tool_name: str,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolResultObserverOutput:
        """观察业务结果并返回可合并的入库状态或警告。"""

        ...

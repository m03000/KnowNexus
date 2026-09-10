"""组合多个领域 ToolKit 并统一注册到 Loop ToolRegistry。

本文件只负责能力装配，不规定 Agent 必须按什么顺序调用工具。调用方可以组合完整工具
集，也可以只给某个 Sub-Agent 暴露最小权限工具集。
"""

from collections.abc import Iterable

from study_help_agent.runtime.tools.core import ToolDefinition, ToolRegistry


class LoopToolSet:
    """保存一组已经去重的 ToolDefinition，并提供统一注册方法。"""

    def __init__(self, tool_groups: Iterable[Iterable[ToolDefinition]]) -> None:
        """合并多个工具组，并在装配阶段发现重复名称。"""

        definitions: list[ToolDefinition] = []
        names: set[str] = set()
        for group in tool_groups:
            for tool in group:
                if tool.name in names:
                    raise ValueError(f"Duplicate tool in LoopToolSet: {tool.name}")
                names.add(tool.name)
                definitions.append(tool)
        self._definitions = tuple(definitions)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回不可变工具定义集合，便于按 Agent 白名单进一步筛选。"""

        return self._definitions

    def register_into(self, registry: ToolRegistry) -> None:
        """把整组工具注册到指定 ToolRegistry。"""

        registry.register_many(self._definitions)

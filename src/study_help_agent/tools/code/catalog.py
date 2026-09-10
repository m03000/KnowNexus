"""代码工具目录，只装配 Code Sub-Agent 的高层业务工具。

"""

from study_help_agent.capabilities.code_analysis.application.service import (
    CodeAnalysisService,
)
from study_help_agent.capabilities.code_analysis.mini_agents import (
    CodeAnalysisMiniAgent,
)
from study_help_agent.runtime.tools import ToolDefinition

from .intelligence import CodeIntelligenceTools


def create_code_tool_groups(
    *,
    mini_agent: CodeAnalysisMiniAgent,
    service: CodeAnalysisService,
) -> tuple[tuple[ToolDefinition, ...], ...]:
    """创建统一代码分析工具组，不包含代码审查和源码写操作。"""

    return (
        CodeIntelligenceTools(
            mini_agent=mini_agent,
            service=service,
        ).definitions(),
    )


def create_code_mutation_tool_groups(**_dependencies) -> tuple:
    """兼容旧导入；代码 Agent 已不再获得独立修改工具。"""

    return ()

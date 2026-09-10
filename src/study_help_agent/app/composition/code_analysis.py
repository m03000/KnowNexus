"""代码解释与代码审查领域的依赖组合模块。"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.core.config import Settings
from study_help_agent.infrastructure.filesystem.safe_path import SafeProjectPathResolver
from study_help_agent.infrastructure.persistence import SqliteConnectionFactory
from study_help_agent.capabilities.code_analysis.llm import CodeAnalysisOperations
from study_help_agent.capabilities.code_analysis.mini_agents import CodeAnalysisMiniAgent
from study_help_agent.capabilities.code_analysis.application import CodeAnalysisService
from study_help_agent.capabilities.code_analysis.infrastructure import (
    FileSystemSourceProjectInspector,
    SqliteCodeAnalysisRepository,
)
from study_help_agent.runtime.tools import ToolDefinition
from study_help_agent.tools import create_code_tool_groups


@dataclass(frozen=True, slots=True)
class CodeAnalysisComposition:
    """代码领域对应用组合根公开的最小装配结果。"""

    analysis_service: CodeAnalysisService
    tool_groups: tuple[tuple[ToolDefinition, ...], ...]


def compose_code_analysis(
    *,
    settings: Settings,
    llm: BaseChatModel,
    database: SqliteConnectionFactory,
    path_resolver: SafeProjectPathResolver,
) -> CodeAnalysisComposition:
    """创建代码服务、具体仓储和默认只读/候选生成工具。"""

    analysis_repository = SqliteCodeAnalysisRepository(connections=database)
    analysis_inspector = FileSystemSourceProjectInspector(
        path_resolver=path_resolver
    )
    analysis_service = CodeAnalysisService(repository=analysis_repository)

    operations = CodeAnalysisOperations(
        llm,
        max_parallelism=settings.code_analysis_max_parallelism,
    )
    mini_agent = CodeAnalysisMiniAgent(
        llm=llm,
        inspector=analysis_inspector,
        operations=operations,
        scan_max_files=settings.source_scan_max_files,
        source_max_bytes=settings.source_file_max_bytes,
        max_parallelism=settings.code_analysis_max_parallelism,
    )
    return CodeAnalysisComposition(
        analysis_service=analysis_service,
        tool_groups=create_code_tool_groups(
            mini_agent=mini_agent,
            service=analysis_service,
        ),
    )

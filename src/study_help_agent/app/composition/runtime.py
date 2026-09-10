"""业务无关的 Artifact 与分析文档工具组合模块。"""

from __future__ import annotations

from study_help_agent.core.config import Settings
from study_help_agent.infrastructure.filesystem import (
    AtomicTextDocumentWriter,
)
from study_help_agent.runtime import (
    ArtifactAccessTools,
    DocumentOutputTools,
    LocalFileReadTools,
)
from study_help_agent.runtime.tools import ToolDefinition


def compose_runtime_tool_groups(
    settings: Settings,
) -> tuple[tuple[ToolDefinition, ...], ...]:
    """创建所有 Agent 共用的 Artifact 读取和分析文档输出工具。"""

    return (
        ArtifactAccessTools().definitions(),
        DocumentOutputTools(
            writer=AtomicTextDocumentWriter(
                output_root=settings.runtime_data_directory / "loop_documents"
            )
        ).definitions(),
        LocalFileReadTools(
            allowed_roots=settings.allowed_project_roots,
            max_file_bytes=min(settings.source_file_max_bytes, 256 * 1024),
        ).definitions(),
    )

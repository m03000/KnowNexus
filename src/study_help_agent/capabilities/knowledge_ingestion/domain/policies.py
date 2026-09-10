"""集中声明自动入库白名单，避免中间产物和查询副本污染知识库。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AutoIngestionPolicy:
    """判断 ToolResult 携带的 Artifact 是否属于最终知识产物。"""

    allowed_artifact_types: frozenset[str] = frozenset(
        {"code_analysis_project", "learning_note_candidate"}
    )
    user_memory_enabled: bool = False
    allow_partial_results: bool = False

    def accepts(self, *, artifact_type: str, partial: bool) -> bool:
        """只有白名单中的完整最终产物才进入自动入库流程。"""

        if partial and not self.allow_partial_results:
            return False
        return artifact_type in self.allowed_artifact_types

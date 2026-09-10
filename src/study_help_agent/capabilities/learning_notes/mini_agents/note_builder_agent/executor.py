"""LearningNoteBuilderGraph 的 NoteBundle 强类型执行入口。"""

from study_help_agent.capabilities.learning_notes.domain import (
    BuiltLearningNote,
    NoteBundle,
)

from .graph import build_learning_note_builder_graph
from .nodes import LearningNoteBuilderNodes


class LearningNoteBuilderMiniAgent:
    """从任意规模文本规划并生成一篇或多篇可验收的专业学习笔记。"""

    def __init__(self, *, nodes: LearningNoteBuilderNodes) -> None:
        self._graph = build_learning_note_builder_graph(nodes)

    def build(
        self,
        *,
        text: str,
        source_type: str = "text",
        source_name: str = "",
        source_uri: str = "",
        source_metadata: dict | None = None,
    ) -> NoteBundle:
        """运行完整规划图；返回候选集合，不执行文件保存或知识库入库。"""

        state = self._graph.invoke(
            {
                "input_text": text,
                "source_type": source_type,
                "source_name": source_name,
                "source_uri": source_uri,
                "source_metadata": dict(source_metadata or {}),
            }
        )
        notes = [
            BuiltLearningNote(
                title=item["title"],
                introduction=item["introduction"],
                content=item["content"],
                topics=item.get("topics", []),
                metadata={
                    **state["metadata"],
                    "note_id": item["note_id"],
                    "source_chunk_ids": item["source_chunk_ids"],
                    "assigned_item_ids": item["assigned_item_ids"],
                    "review_summary": item.get("review_summary", ""),
                },
                source_structure_reasonable=state["plan"]["source_structure_reasonable"],
                processing_notes=item.get("processing_notes", []),
                quality_status=(
                    "completed" if item.get("quality_passed") else "partial"
                ),
                quality_issues=item.get("quality_issues", []),
                revision_count=int(item.get("revision_count", 0)),
                source_chunk_ids=item["source_chunk_ids"],
                covered_item_ids=item.get("covered_item_ids", []),
            )
            for item in state["generated_notes"]
        ]
        return NoteBundle(
            title=state["plan"]["bundle_title"],
            introduction=state["plan"]["bundle_introduction"],
            strategy=state["plan"]["strategy"],
            notes=notes,
            audit_summary=state["plan"]["audit_summary"],
            planning_rationale=state["plan"]["rationale"],
            metadata=state["metadata"],
            status=state["status"],
            warnings=state.get("warnings", []),
        )

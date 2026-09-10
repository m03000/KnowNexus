"""把最终学习笔记 Artifact 投影到个人知识空间。"""

from __future__ import annotations

from typing import Any, Mapping

from study_help_agent.runtime.artifacts.store import StoredArtifact
from study_help_agent.runtime.serialization import to_serializable

from ...domain.enums import KnowledgeAssetType, KnowledgeSpace
from ...domain.models import KnowledgeAssetDraft


class LearningNoteProjector:
    """只接收已经完成规划、生成和审查的单篇笔记候选。"""

    artifact_type = "learning_note_candidate"

    def project(self, artifact: StoredArtifact) -> tuple[KnowledgeAssetDraft, ...]:
        """保留笔记正文和来源元数据，生成一个稳定知识资产。"""

        data = to_serializable(artifact.content)
        if not isinstance(data, Mapping):
            raise TypeError("learning_note_candidate content must be an object")
        title = str(data.get("title") or artifact.name).strip()
        introduction = str(data.get("introduction") or "").strip()
        body = str(data.get("content") or "").strip()
        if not body:
            raise ValueError("learning_note_candidate has no note content")
        content = f"# {title}\n\n"
        if introduction:
            content += f"> {introduction}\n\n"
        content += body
        source_key = self._source_key(artifact=artifact, data=data, title=title)
        metadata: dict[str, Any] = {
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "topics": list(data.get("topics") or ()),
            "quality_status": data.get("quality_status", "completed"),
            "source_chunk_ids": list(data.get("source_chunk_ids") or ()),
            **dict(data.get("metadata") or {}),
        }
        return (
            KnowledgeAssetDraft(
                space=KnowledgeSpace.PERSONAL_KNOWLEDGE,
                asset_type=KnowledgeAssetType.LEARNING_NOTE,
                stable_source_key=source_key,
                title=title,
                content=content,
                metadata=metadata,
            ),
        )

    @staticmethod
    def _source_key(
        *, artifact: StoredArtifact, data: Mapping[str, Any], title: str
    ) -> str:
        """优先使用显式 note_id/source_id，否则退回 Artifact 的稳定 ID。"""

        metadata = data.get("metadata") or {}
        if isinstance(metadata, Mapping):
            filename = metadata.get("display_filename")
            if filename:
                return f"note-file:{filename}"
            explicit = metadata.get("note_id") or metadata.get("source_id")
            if explicit:
                return f"note:{explicit}"
        return f"note:{artifact.artifact_id}:{title}"

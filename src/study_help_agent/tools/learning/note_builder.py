"""学习笔记构建 Agent 的工具适配层。

本工具允许 Learning Sub-Agent 直接提交干净文本，也允许消费前置资源工具产生的文本
Artifact。它只生成候选笔记，不自动保存文件或写入知识库。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from study_help_agent.capabilities.learning_notes.mini_agents import (
    LearningNoteBuilderMiniAgent,
)
from study_help_agent.capabilities.learning_notes.application.service import (
    LearningNoteService,
)
from study_help_agent.runtime.serialization import to_serializable
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult


class LearningNoteBuilderTools:
    """向 Agent 暴露内容审查、动态规划和多笔记质量闭环。"""

    def __init__(
        self,
        *,
        mini_agent: LearningNoteBuilderMiniAgent,
        note_service: LearningNoteService,
    ) -> None:
        self._mini_agent = mini_agent
        self._note_service = note_service

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回 LLM 可见的工具描述和输入 Schema。"""

        return (
            ToolDefinition(
                name="build_learning_note",
                description=(
                    "核心学习笔记规划与生成工具。先按规模切块并审查内容和全局结构，再动态"
                    "规划一篇或多篇专业笔记；长材料会并行分块审查和多篇生成。最终检查来源"
                    "忠实度与信息覆盖，失败时最多修订一次。目标是专业重组而非照搬或摘要。"
                    "text 与 source_artifact_id 必须且只能提供一个；通过质量闭环的结果会自动保存供前端展示。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source_artifact_id": {"type": "string"},
                        "source_type": {
                            "type": "string",
                            "description": "来源类型，如 text、document、video_transcript。",
                        },
                        "source_name": {"type": "string"},
                        "source_uri": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=self.build,
            ),
        )

    @staticmethod
    def _artifact_text(content: Any) -> str:
        """从字符串或常见文本 Artifact 对象中取得正文。"""

        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            for key in ("cleaned_text", "text", "content"):
                value = content.get(key)
                if isinstance(value, str):
                    return value
        raise TypeError("来源 Artifact 必须包含字符串 text、cleaned_text 或 content")

    def build(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """解析直接文本或 Artifact，运行笔记图并保存候选 Artifact。"""

        direct_text = arguments.get("text")
        source_artifact_id = arguments.get("source_artifact_id")
        if (direct_text is None) == (source_artifact_id is None):
            raise ValueError("text 与 source_artifact_id 必须且只能提供一个")
        if source_artifact_id is not None:
            source = context.artifact_store.get(str(source_artifact_id))
            text = self._artifact_text(source.content)
            source_metadata = (
                source.content.get("metadata", {})
                if isinstance(source.content, Mapping)
                else {}
            )
        else:
            text = str(direct_text)
            source_metadata = {}
        bundle = self._mini_agent.build(
            text=text,
            source_type=str(
                arguments.get("source_type")
                or source_metadata.get("source_type")
                or "text"
            ),
            source_name=str(
                arguments.get("source_name")
                or source_metadata.get("source_name")
                or ""
            ),
            source_uri=str(
                arguments.get("source_uri")
                or source_metadata.get("source_uri")
                or ""
            ),
            source_metadata=dict(source_metadata),
        )
        saved_notes = [self._note_service.publish(note) for note in bundle.notes]
        note_artifacts = [
            context.artifact_store.put(
                artifact_type="learning_note_candidate",
                name=note.title,
                summary=(
                    "学习笔记候选已生成并通过质量审查。"
                    if note.quality_status == "completed"
                    else "学习笔记候选已生成，但仍存在质量警告。"
                ),
                content={
                    **to_serializable(note),
                    "metadata": {
                        **dict(note.metadata),
                        "display_filename": saved.filename,
                        "display_path": saved.path,
                    },
                },
            )
            for note, saved in zip(bundle.notes, saved_notes, strict=True)
        ]
        note_references = [
            {
                "artifact_id": artifact.artifact_id,
                "title": note.title,
                "introduction": note.introduction,
                "topics": note.topics,
                "quality_status": note.quality_status,
                "source_chunk_ids": note.source_chunk_ids,
                "filename": saved.filename,
                "path": saved.path,
            }
            for artifact, note, saved in zip(
                note_artifacts, bundle.notes, saved_notes, strict=True
            )
        ]
        source_name = str(
            arguments.get("source_name")
            or source_metadata.get("source_name")
            or "未命名来源"
        )
        source_uri = str(
            arguments.get("source_uri")
            or source_metadata.get("source_uri")
            or source_metadata.get("url")
            or ""
        )
        topic_preview = "、".join(
            dict.fromkeys(topic for note in bundle.notes for topic in note.topics)
        )[:240]
        bundle_artifact = context.artifact_store.put(
            artifact_type="learning_note_bundle",
            name=bundle.title,
            summary=(
                f"来源《{source_name}》的笔记已生成：{bundle.title}；"
                f"内容简介：{bundle.introduction[:320]}；"
                f"核心知识点：{topic_preview or '以笔记正文为准'}。"
            ),
            content={
                "title": bundle.title,
                "introduction": bundle.introduction,
                "strategy": bundle.strategy,
                "audit_summary": bundle.audit_summary,
                "planning_rationale": bundle.planning_rationale,
                "notes": note_references,
                "saved_notes": [to_serializable(item) for item in saved_notes],
                "metadata": bundle.metadata,
                "status": bundle.status,
                "warnings": bundle.warnings,
            },
        )
        artifact_ids = (
            bundle_artifact.artifact_id,
            *(artifact.artifact_id for artifact in note_artifacts),
        )
        quality_warnings = list(bundle.warnings)
        quality_warnings.extend(
            issue for note in bundle.notes for issue in note.quality_issues
        )
        return ToolResult(
            summary=bundle_artifact.summary,
            payload={
                "completed_item": bundle.status == "completed",
                # 该工具一次只处理一个已经准备好的来源；质量通过并保存后，
                # 对当前单资源任务而言已经具备直接结束条件。
                "task_completed": bundle.status == "completed",
                "final_answer_hint": bundle_artifact.summary,
                "source_identity": source_uri or source_name,
                "source_name": source_name,
                "source_uri": source_uri,
                "artifact_id": bundle_artifact.artifact_id,
                "bundle_artifact_id": bundle_artifact.artifact_id,
                "note_artifact_ids": [item["artifact_id"] for item in note_references],
                "note_artifact_id": (
                    note_references[0]["artifact_id"]
                    if len(note_references) == 1 else None
                ),
                "title": bundle.title,
                "introduction": bundle.introduction,
                "strategy": bundle.strategy,
                "notes": note_references,
                "note_count": len(note_references),
                "metadata": bundle.metadata,
                "quality_status": bundle.status,
            },
            artifact_ids=artifact_ids,
            warnings=tuple(dict.fromkeys(quality_warnings)),
            partial=bundle.status != "completed",
        )

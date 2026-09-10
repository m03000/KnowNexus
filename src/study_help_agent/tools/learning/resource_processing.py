"""资源获取、内容提取和深度标准化三个按需工具。

工具之间只通过 Artifact ID 传递大型内容：获取工具产生原始资源，提取工具产生文本或
视频双文本，标准化工具融合高噪声内容。普通文本无需调用它们，可直接进入笔记构建。
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from study_help_agent.capabilities.learning_notes.application import (
    LearningResourceService,
)
from study_help_agent.capabilities.learning_notes.domain import (
    AcquiredResource,
    ExtractedContent,
    TranscriptSegment,
)
from study_help_agent.capabilities.learning_notes.llm import (
    LearningContentNormalizerOperations,
)
from study_help_agent.observability.context import submit_with_trace
from study_help_agent.runtime.serialization import to_serializable
from study_help_agent.runtime.streaming import StreamEvent
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult


class LearningResourceTools:
    """向 Learning Agent 暴露三个彼此独立、可按需组合的资源工具。"""

    def __init__(
        self,
        *,
        service: LearningResourceService,
        normalizer: LearningContentNormalizerOperations,
    ) -> None:
        self._service = service
        self._normalizer = normalizer

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回获取、提取和深度标准化工具的 LLM 可见定义。"""

        return (
            ToolDefinition(
                name="merge_text_files",
                description=(
                    "读取并合并多个本地文本文件的文本内容，支持 txt、md、markdown 和 docx。"
                    "按输入顺序纯提取正文，为每个来源补充文件名、格式、原始路径、字符数等元信息，"
                    "再生成一个可交给 build_learning_note 的长文本 Artifact。"
                    "适合把多个短文档或多篇本地笔记合成一份笔记材料；"
                    "只允许可以直接读取文本的场合，不用于 PDF、图片、音视频或需要语义去噪的资源。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "file_paths": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 2,
                            "maxItems": 50,
                            "description": "按合并顺序提供的 2～50 个本地文件绝对路径。",
                        },
                        "title": {
                            "type": "string",
                            "description": "可选的合并材料标题；不提供时使用“合并文本材料”。",
                        },
                    },
                    "required": ["file_paths"],
                    "additionalProperties": False,
                },
                handler=self.merge_text_files,
            ),
            ToolDefinition(
                name="acquire_resources_batch",
                description=(
                    "并发获取一组彼此独立的外部链接或本地资源，按输入顺序返回每项结果。"
                    "每个成功项生成独立 acquired_resource Artifact；单项失败不会中断整批。"
                    "适合多来源笔记，只有一个来源时使用 acquire_external_resource。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "sources": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 2,
                            "maxItems": 20,
                        }
                    },
                    "required": ["sources"],
                    "additionalProperties": False,
                },
                handler=self.acquire_batch,
            ),
            ToolDefinition(
                name="extract_resources_batch",
                description=(
                    "并发提取多个 acquired_resource Artifact 的正文、OCR、音频或视频双文本，"
                    "每个成功项生成独立 extracted_content Artifact，并保持输入顺序。"
                    "单项失败会作为部分失败返回，便于 Agent 决定重试或跳过。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_artifact_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 2,
                            "maxItems": 20,
                        }
                    },
                    "required": ["resource_artifact_ids"],
                    "additionalProperties": False,
                },
                handler=self.extract_batch,
            ),
            ToolDefinition(
                name="acquire_external_resource",
                description=(
                    "按需获取外部链接或本地文件并复制到受控资源目录。"
                    "平台视频使用yt-dlp，普通文件使用限流下载；"
                    "只负责获取，不提取内容。纯文本输入不应调用此工具。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
                handler=self.acquire,
            ),
            ToolDefinition(
                name="extract_resource_content",
                description=(
                    "从 acquired_resource Artifact 提取内容。"
                    "支持文本、HTML、Word、PDF、图片OCR、音频转写和视频音频/画面双文本；"
                    "只提取资源的内容生成文本内容，不进行语义改写。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_artifact_id": {"type": "string"}
                    },
                    "required": ["resource_artifact_id"],
                    "additionalProperties": False,
                },
                handler=self.extract,
            ),
            ToolDefinition(
                name="normalize_learning_content",
                description=(
                    "仅对明显高噪声文本、OCR结果或音视频双文本执行深度去噪与音画融合。"
                    "目标是保留内容而非总结。可读取 extracted_content Artifact 或直接文本；"
                    "普通干净文档应跳过此工具直接调用 build_learning_note。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "source_artifact_id": {"type": "string"},
                        "text": {"type": "string"},
                        "source_type": {"type": "string"},
                        "source_name": {"type": "string"},
                        "source_uri": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                handler=self.normalize,
            ),
        )

    def acquire_batch(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """受控并发获取资源，主线程按原始顺序写入 Artifact Store。"""

        sources = self._validate_string_batch(arguments.get("sources"), "sources")
        completed = self._run_ordered_batch(sources, self._service.acquire)
        items: list[dict[str, Any]] = []
        artifact_ids: list[str] = []
        warnings: list[str] = []
        for index, (source, outcome) in enumerate(zip(sources, completed)):
            if isinstance(outcome, Exception):
                message = f"资源 {index + 1} 获取失败：{source}；{outcome}"
                warnings.append(message)
                items.append({"index": index, "source": source, "status": "failed", "error": str(outcome)})
                continue
            resource = outcome
            artifact = context.artifact_store.put(
                artifact_type="acquired_resource",
                name=resource.file_name,
                summary=f"学习资源已获取：{resource.file_name}",
                content=to_serializable(resource),
            )
            artifact_ids.append(artifact.artifact_id)
            items.append({
                "index": index,
                "source": source,
                "status": "success",
                "artifact_id": artifact.artifact_id,
                "file_name": resource.file_name,
                "source_type": resource.source_type,
                "media_type": resource.media_type,
                "size_bytes": resource.size_bytes,
            })
        return ToolResult(
            summary=f"批量获取完成：成功 {len(artifact_ids)}/{len(sources)} 个资源。",
            payload={"items": items, "success_count": len(artifact_ids), "total_count": len(sources)},
            artifact_ids=tuple(artifact_ids),
            warnings=tuple(warnings),
            partial=bool(warnings),
        )

    def extract_batch(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """校验一批资源 Artifact，并发提取后在主线程持久化结果。"""

        source_ids = self._validate_string_batch(
            arguments.get("resource_artifact_ids"), "resource_artifact_ids"
        )
        resources: list[AcquiredResource | Exception] = []
        for artifact_id in source_ids:
            try:
                source = context.artifact_store.get(artifact_id)
                if source.artifact_type != "acquired_resource" or not isinstance(source.content, Mapping):
                    raise TypeError("内容提取工具只接受 acquired_resource Artifact")
                resources.append(AcquiredResource(**dict(source.content)))
            except Exception as error:  # 单项错误必须保留整批可恢复性
                resources.append(error)

        valid_indexes = [index for index, item in enumerate(resources) if not isinstance(item, Exception)]
        valid_resources = [resources[index] for index in valid_indexes]
        extracted_outcomes = self._run_ordered_batch(valid_resources, self._service.extract)
        outcomes: list[ExtractedContent | Exception] = [
            item if isinstance(item, Exception) else RuntimeError("资源未执行") for item in resources
        ]
        for index, outcome in zip(valid_indexes, extracted_outcomes):
            outcomes[index] = outcome

        items: list[dict[str, Any]] = []
        artifact_ids: list[str] = []
        warnings: list[str] = []
        for index, (source_id, outcome) in enumerate(zip(source_ids, outcomes)):
            if isinstance(outcome, Exception):
                warnings.append(f"资源 {index + 1} 提取失败：{source_id}；{outcome}")
                items.append({"index": index, "resource_artifact_id": source_id, "status": "failed", "error": str(outcome)})
                continue
            extracted = outcome
            resource = resources[index]
            assert isinstance(resource, AcquiredResource)
            artifact = context.artifact_store.put(
                artifact_type="extracted_content",
                name=resource.file_name,
                summary=f"内容提取完成：正文 {len(extracted.text)} 字符。",
                content=to_serializable(extracted),
            )
            artifact_ids.append(artifact.artifact_id)
            item_warnings = [str(item) for item in extracted.warnings]
            warnings.extend(item_warnings)
            items.append({
                "index": index,
                "resource_artifact_id": source_id,
                "status": "success",
                "artifact_id": artifact.artifact_id,
                "file_name": resource.file_name,
                "text_characters": len(extracted.text),
                "audio_segments": len(extracted.audio_transcript),
                "visual_segments": len(extracted.visual_transcript),
                "warnings": item_warnings,
            })
        return ToolResult(
            summary=f"批量提取完成：成功 {len(artifact_ids)}/{len(source_ids)} 个资源。",
            payload={"items": items, "success_count": len(artifact_ids), "total_count": len(source_ids)},
            artifact_ids=tuple(artifact_ids),
            warnings=tuple(warnings),
            partial=bool(warnings),
        )

    @staticmethod
    def _validate_string_batch(value: Any, field_name: str) -> list[str]:
        """验证批量参数并去除空白，保留用户给定顺序。"""

        if not isinstance(value, list) or not 2 <= len(value) <= 20:
            raise ValueError(f"{field_name} 必须包含 2～20 个值")
        values = [str(item).strip() for item in value]
        if any(not item for item in values):
            raise ValueError(f"{field_name} 不能包含空值")
        return values

    @staticmethod
    def _run_ordered_batch(values: list[Any], operation) -> list[Any]:
        """最多四路并发执行独立任务，并把结果恢复到输入顺序。"""

        results: list[Any] = [RuntimeError("任务未执行") for _ in values]
        with ThreadPoolExecutor(max_workers=min(4, len(values))) as executor:
            futures = {
                submit_with_trace(executor, operation, value): index
                for index, value in enumerate(values)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as error:  # 工具层需要向 Agent 返回逐项失败
                    results[index] = error
        return results

    def merge_text_files(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """确定性提取多个文本文件并合并为带来源元数据的长文本 Artifact。"""

        raw_paths = arguments.get("file_paths")
        if not isinstance(raw_paths, list) or not 2 <= len(raw_paths) <= 50:
            raise ValueError("file_paths 必须包含 2～50 个本地文本文件路径")

        allowed_suffixes = {".txt", ".md", ".markdown", ".docx"}
        title = str(arguments.get("title") or "合并文本材料").strip()
        sections: list[str] = [
            f"# {title}",
            "",
            f"> 本文档由 {len(raw_paths)} 个本地文本文件按用户给定顺序确定性合并；"
            "未经过 LLM 改写、总结或去噪。",
        ]
        sources: list[dict[str, Any]] = []
        warnings: list[str] = []

        for index, raw_path in enumerate(raw_paths, start=1):
            source_path = str(raw_path).strip()
            suffix = Path(source_path).suffix.lower()
            if suffix not in allowed_suffixes:
                raise ValueError(
                    f"仅支持 txt、md、markdown、docx 文本文件：{source_path}"
                )
            resource = self._service.acquire(source_path)
            extracted = self._service.extract(resource)
            text = extracted.text.strip()
            if not text:
                raise ValueError(f"文件没有提取到文本内容：{source_path}")

            source_metadata = {
                "index": index,
                "file_name": resource.file_name,
                "format": suffix.lstrip("."),
                "source_uri": resource.source_uri,
                "original_path": resource.metadata.get("original_path", source_path),
                "size_bytes": resource.size_bytes,
                "characters": len(text),
                "extraction_mode": extracted.metadata.get("extraction_mode", "text"),
            }
            sources.append(source_metadata)
            warnings.extend(str(item) for item in extracted.warnings)
            sections.extend((
                "",
                "---",
                "",
                f"## 来源 {index}：{resource.file_name}",
                "",
                f"> 格式：{source_metadata['format']} · "
                f"原始路径：{source_metadata['original_path']} · "
                f"字符数：{source_metadata['characters']}",
                "",
                text,
            ))

        merged_text = "\n".join(sections).strip()
        metadata = {
            "source_type": "merged_documents",
            "source_name": title,
            "source_uri": "",
            "document_count": len(sources),
            "sources": sources,
            "merge_strategy": "ordered_concatenation",
            "llm_used": False,
        }
        artifact = context.artifact_store.put(
            artifact_type="merged_text_content",
            name=title,
            summary=(
                f"已确定性合并 {len(sources)} 个文本文件，共 {len(merged_text)} 字符；"
                "可继续调用 build_learning_note。"
            ),
            content={"text": merged_text, "metadata": metadata},
        )
        return ToolResult(
            summary=artifact.summary,
            payload={
                "artifact_id": artifact.artifact_id,
                "document_count": len(sources),
                "merged_characters": len(merged_text),
                "sources": sources,
                "metadata": metadata,
            },
            artifact_ids=(artifact.artifact_id,),
            warnings=tuple(dict.fromkeys(warnings)),
            partial=bool(warnings),
        )

    def acquire(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """获取资源并保存不向 Prompt 展开本地路径的 acquired_resource Artifact。"""

        resource = self._service.acquire(str(arguments["source"]))
        artifact = context.artifact_store.put(
            artifact_type="acquired_resource",
            name=resource.file_name,
            summary=f"学习资源已获取：{resource.file_name}",
            content=to_serializable(resource),
        )
        return ToolResult(
            summary=artifact.summary,
            payload={
                "artifact_id": artifact.artifact_id,
                "resource_id": resource.resource_id,
                "file_name": resource.file_name,
                "source_type": resource.source_type,
                "media_type": resource.media_type,
                "size_bytes": resource.size_bytes,
                "metadata": resource.metadata,
            },
            artifact_ids=(artifact.artifact_id,),
        )

    def extract(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """读取受控资源 Artifact 并生成统一 extracted_content Artifact。"""

        source = context.artifact_store.get(str(arguments["resource_artifact_id"]))
        if source.artifact_type != "acquired_resource" or not isinstance(
            source.content, Mapping
        ):
            raise TypeError("内容提取工具只接受 acquired_resource Artifact")
        resource = AcquiredResource(**dict(source.content))
        extracted = self._service.extract(
            resource,
            progress=lambda stage, message: self._emit_extraction_progress(
                context, stage=stage, message=message
            ),
        )
        artifact = context.artifact_store.put(
            artifact_type="extracted_content",
            name=resource.file_name,
            summary=(
                f"内容提取完成：正文 {len(extracted.text)} 字符，"
                f"音频 {len(extracted.audio_transcript)} 段，"
                f"画面 {len(extracted.visual_transcript)} 段。"
            ),
            content=to_serializable(extracted),
        )
        # 视频在音频转写与画面 OCR 完成后已不再参与后续步骤。这里只清理
        # acquirer 创建的受控副本；PDF、Word 等文档保留，供笔记回溯来源。
        source_suffix = Path(resource.local_path).suffix.lower()
        source_retained = source_suffix not in {
            ".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv"
        }
        if not source_retained:
            self._service.release(resource)
        return ToolResult(
            summary=artifact.summary,
            payload={
                "artifact_id": artifact.artifact_id,
                "text_characters": len(extracted.text),
                "audio_segments": len(extracted.audio_transcript),
                "visual_segments": len(extracted.visual_transcript),
                "metadata": extracted.metadata,
                "source_file_retained": source_retained,
            },
            artifact_ids=(artifact.artifact_id,),
            warnings=tuple(extracted.warnings),
            partial=bool(extracted.warnings),
        )

    @staticmethod
    def _emit_extraction_progress(
        context: ToolExecutionContext, *, stage: str, message: str
    ) -> None:
        """Forward deterministic extraction stages to the existing event stream."""

        if context.event_sink is None:
            return
        try:
            context.event_sink(StreamEvent(
                event="note_pipeline_progress",
                run_id=context.run_id,
                agent="note",
                data={"stage": stage, "status": "running", "message": message},
            ))
        except Exception:
            return

    def normalize(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """深度清洗直接文本，或融合 extracted_content 中的多模态文本。"""

        direct_text = arguments.get("text")
        artifact_id = arguments.get("source_artifact_id")
        if (direct_text is None) == (artifact_id is None):
            raise ValueError("text 与 source_artifact_id 必须且只能提供一个")
        if artifact_id is not None:
            source = context.artifact_store.get(str(artifact_id))
            if source.artifact_type != "extracted_content" or not isinstance(
                source.content, Mapping
            ):
                raise TypeError("标准化 Artifact 输入必须是 extracted_content")
            extracted = self._restore_extracted(source.content)
        else:
            extracted = ExtractedContent(
                resource_id="direct_text",
                text=str(direct_text),
                metadata={
                    "source_type": str(arguments.get("source_type", "text")),
                    "source_name": str(arguments.get("source_name", "")),
                    "source_uri": str(arguments.get("source_uri", "")),
                },
            )
        normalized = self._normalizer.normalize(extracted)
        artifact = context.artifact_store.put(
            artifact_type="clean_content",
            name=str(normalized.metadata.get("source_name") or "clean-content"),
            summary=f"内容标准化完成：{len(normalized.cleaned_text)} 字符。",
            content=to_serializable(normalized),
        )
        return ToolResult(
            summary=artifact.summary,
            payload={
                "artifact_id": artifact.artifact_id,
                "cleaned_characters": len(normalized.cleaned_text),
                "processing_notes": normalized.processing_notes,
                "metadata": normalized.metadata,
            },
            artifact_ids=(artifact.artifact_id,),
            warnings=tuple(normalized.warnings),
            partial=bool(normalized.warnings),
        )

    @staticmethod
    def _restore_extracted(content: Mapping[str, Any]) -> ExtractedContent:
        """把 JSON 兼容 Artifact 恢复成强类型提取结果。"""

        return ExtractedContent(
            resource_id=str(content.get("resource_id", "")),
            text=str(content.get("text", "")),
            audio_transcript=[
                TranscriptSegment(**dict(item))
                for item in content.get("audio_transcript", [])
                if isinstance(item, Mapping)
            ],
            visual_transcript=[
                TranscriptSegment(**dict(item))
                for item in content.get("visual_transcript", [])
                if isinstance(item, Mapping)
            ],
            metadata=dict(content.get("metadata", {})),
            warnings=[str(item) for item in content.get("warnings", [])],
        )

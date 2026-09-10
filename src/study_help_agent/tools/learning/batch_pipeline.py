"""Note Agent 的高层批量流水线工具。

本文件把资源获取、提取、质量评估、按需清洗和笔记生成组合成受控并发流程。
外层 Agent 只负责选择该能力和汇总结果，不再逐个资源手工推进底层工具。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Lock
from time import sleep
from typing import Any, Mapping

from study_help_agent.observability.context import submit_with_trace
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult
from study_help_agent.runtime.streaming import StreamEvent
from study_help_agent.runtime.cancellation import AgentCancelledError

from .note_builder import LearningNoteBuilderTools
from .resource_processing import LearningResourceTools


@dataclass(frozen=True, slots=True)
class ContentQualityMetrics:
    """用低成本规则描述提取文本质量，避免每个资源先调用 LLM 判断。"""

    text_characters: int
    audio_segments: int
    visual_segments: int
    duplicate_ratio: float
    suspicious_character_ratio: float
    has_warnings: bool

    @property
    def unusable(self) -> bool:
        return self.text_characters == 0 and self.audio_segments == 0

    @property
    def needs_normalization(self) -> bool:
        return (
            self.audio_segments > 0
            or self.visual_segments > 0
            or self.duplicate_ratio >= 0.25
            or self.suspicious_character_ratio >= 0.08
            or self.has_warnings
        )


class LearningNotePipelineTools:
    """向 Note Agent 暴露单资源和批量资源两个完整用例。"""

    def __init__(
        self,
        *,
        resources: LearningResourceTools,
        notes: LearningNoteBuilderTools,
        max_parallelism: int = 3,
        acquire_attempts: int = 2,
        extract_attempts: int = 2,
    ) -> None:
        self._resources = resources
        self._notes = notes
        self._max_parallelism = max(1, max_parallelism)
        self._acquire_attempts = max(1, acquire_attempts)
        self._extract_attempts = max(1, extract_attempts)
        self._stage_cache: dict[str, dict[str, Any]] = {}
        self._cache_lock = Lock()

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回高层用例工具；底层步骤不再要求 Note Agent 逐个编排。"""

        return (
            ToolDefinition(
                name="build_single_learning_note",
                description=(
                    "从一个外部链接或本地资源完成获取、提取、质量检测、按需清洗、笔记生成与保存。"
                    "返回内容概括、核心知识点、缓存和阶段状态。"
                ),
                parameters={
                    "type": "object",
                    "properties": {"source": {"type": "string", "minLength": 1}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
                handler=self.build_single,
            ),
            ToolDefinition(
                name="build_learning_notes_batch",
                description=(
                    "并发处理 2～20 个独立链接或本地资源。每个资源拥有独立阶段状态，"
                    "单项失败不阻塞其他项；内部自动重试临时获取错误并按需执行清洗。"
                    "调用一次即可获得整个批次的成功、失败、笔记摘要和核心要点。"
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
                handler=self.build_batch,
            ),
        )

    def build_single(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext,
    ) -> ToolResult:
        """运行一个来源的完整流水线并返回统一批次格式。"""

        source = str(arguments["source"]).strip()
        item = self._process_source(source, context)
        return self._result_from_items([item])

    def build_batch(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext,
    ) -> ToolResult:
        """按有界并发处理独立来源，保持输入顺序聚合结果。"""

        raw_sources = arguments.get("sources")
        if not isinstance(raw_sources, (list, tuple)) or not 2 <= len(raw_sources) <= 20:
            raise ValueError("sources 必须包含 2～20 个资源")
        sources = [str(item).strip() for item in raw_sources]
        if any(not item for item in sources):
            raise ValueError("sources 不能包含空值")

        self._emit_progress(
            context,
            stage="batch",
            status="started",
            message=f"已识别 {len(sources)} 个独立资源，开始并行处理",
        )

        items: list[dict[str, Any] | None] = [None] * len(sources)
        executor = ThreadPoolExecutor(
            max_workers=min(self._max_parallelism, len(sources)),
            thread_name_prefix="note-pipeline",
        )
        cancelled = False
        futures = {}
        try:
            futures = {
                submit_with_trace(executor, self._process_source, source, context): index
                for index, source in enumerate(sources)
            }
            for future in as_completed(futures):
                if context.cancellation_token is not None:
                    context.cancellation_token.raise_if_cancelled()
                index = futures[future]
                try:
                    items[index] = future.result()
                except AgentCancelledError:
                    cancelled = True
                    raise
                except Exception as error:
                    items[index] = self._failed_item(sources[index], "pipeline", error)
        except AgentCancelledError:
            cancelled = True
            for future in futures:
                future.cancel()
            raise
        finally:
            executor.shutdown(wait=not cancelled, cancel_futures=cancelled)
        completed_count = sum(
            item is not None and item.get("status") == "completed" for item in items
        )
        self._emit_progress(
            context,
            stage="batch",
            status="completed",
            message=f"批量处理结束：成功 {completed_count}/{len(sources)} 个资源",
        )
        return self._result_from_items([item for item in items if item is not None])

    def _process_source(
        self, source: str, context: ToolExecutionContext,
    ) -> dict[str, Any]:
        """推进一个来源的状态机；缓存使失败重试不必重做已成功阶段。"""

        token = context.cancellation_token
        if token is not None:
            token.raise_if_cancelled()
        with self._cache_lock:
            state = dict(self._stage_cache.get(source, {}))
        if state.get("status") == "completed":
            return {**state, "cache_hit": True}

        try:
            acquired_id = state.get("acquired_artifact_id")
            if not acquired_id:
                self._emit_progress(
                    context, source=source, stage="acquire", status="running",
                    message="正在获取资源",
                )
                acquired = self._acquire_with_retry(source, context)
                acquired_id = str(acquired.payload["artifact_id"])
                state.update({
                    "source": source,
                    "source_name": str(acquired.payload.get("file_name") or source),
                    "acquired_artifact_id": acquired_id,
                    "acquire_status": "completed",
                })
                self._save_cache(source, state)
                self._emit_progress(
                    context, source=source, stage="acquire", status="completed",
                    message=f"资源获取完成：{state['source_name']}",
                )

            extracted_id = state.get("extracted_artifact_id")
            if not extracted_id:
                extract_attempt = int(state.get("extract_attempts", 0)) + 1
                state.update({
                    "extract_attempts": extract_attempt,
                })
                self._save_cache(source, state)
                self._emit_progress(
                    context, source=source, stage="extract", status="running",
                    message=(
                        "正在提取音频转写与画面文字"
                        if extract_attempt == 1
                        else "正在重新执行媒体提取；已复用下载结果，不会重复下载"
                    ),
                )
                extracted = self._resources.extract(
                    {"resource_artifact_id": acquired_id},
                    context,
                )
                extracted_id = str(extracted.payload["artifact_id"])
                metrics = self._quality_metrics(
                    context.artifact_store.get(extracted_id).content,
                    extracted.warnings,
                )
                if metrics.unusable:
                    raise ValueError("资源没有提取出可用于笔记生成的文本")
                state.update({
                    "extracted_artifact_id": extracted_id,
                    "extract_status": "completed",
                    "quality_metrics": self._metrics_dict(metrics),
                    "warnings": list(extracted.warnings),
                })
                self._save_cache(source, state)
                self._emit_progress(
                    context, source=source, stage="extract", status="completed",
                    message=(
                        f"内容提取完成：音频 {metrics.audio_segments} 段，"
                        f"画面 {metrics.visual_segments} 段"
                    ),
                )
            else:
                metrics = ContentQualityMetrics(**state["quality_metrics"])

            note_input_id = extracted_id
            if metrics.needs_normalization:
                clean_id = state.get("clean_artifact_id")
                if not clean_id:
                    self._emit_progress(
                        context, source=source, stage="normalize", status="running",
                        message="正在融合音画文本并清理识别噪声，不压缩有效内容",
                    )
                    normalized = self._resources.normalize(
                        {
                            "source_artifact_id": extracted_id,
                            "source_name": state["source_name"],
                            "source_uri": source,
                        },
                        context,
                    )
                    clean_id = str(normalized.payload["artifact_id"])
                    state.update({
                        "clean_artifact_id": clean_id,
                        "normalization_status": "completed",
                    })
                    self._save_cache(source, state)
                    self._emit_progress(
                        context, source=source, stage="normalize", status="completed",
                        message="音画文本融合完成，已保留可用解释、示例和细节",
                    )
                note_input_id = clean_id
            else:
                state["normalization_status"] = "skipped"

            if token is not None:
                token.raise_if_cancelled()
            self._emit_progress(
                context, source=source, stage="build_note", status="running",
                message="正在规划正文结构、生成笔记并建立核心知识点关联",
            )
            source_type = (
                "video_transcript"
                if metrics.audio_segments or metrics.visual_segments
                else "external_document"
            )
            note_result = self._notes.build(
                {
                    "source_artifact_id": note_input_id,
                    "source_name": state["source_name"],
                    "source_uri": source,
                    "source_type": source_type,
                },
                context,
            )
            state.update({
                "status": "completed",
                "note_status": "completed",
                "cache_hit": False,
                "bundle_artifact_id": note_result.payload["bundle_artifact_id"],
                "note_artifact_ids": list(note_result.payload["note_artifact_ids"]),
                "title": note_result.payload["title"],
                "introduction": note_result.payload["introduction"],
                "notes": list(note_result.payload["notes"]),
                "core_topics": list(dict.fromkeys(
                    topic
                    for note in note_result.payload["notes"]
                    for topic in note.get("topics", [])
                ))[:12],
            })
            self._save_cache(source, state)
            self._emit_progress(
                context, source=source, stage="build_note", status="completed",
                message=f"笔记生成并保存完成：{state['title']}",
            )
            return state
        except AgentCancelledError:
            raise
        except Exception as error:
            stage = self._current_stage(state)
            attempt = int(state.get("extract_attempts", 0)) if stage == "extract" else 0
            retryable = self._is_retryable_failure(stage, error)
            if stage == "extract" and attempt >= self._extract_attempts:
                retryable = False
            failed = {
                **state,
                **self._failed_item(
                    source,
                    stage,
                    error,
                    retryable=retryable,
                    attempt=attempt,
                    max_attempts=self._extract_attempts if stage == "extract" else 1,
                ),
            }
            self._save_cache(source, failed)
            self._emit_progress(
                context, source=source, stage=failed["failed_stage"], status="failed",
                message=f"当前资源处理失败：{failed['error']}",
            )
            return failed

    @staticmethod
    def _emit_progress(
        context: ToolExecutionContext,
        *,
        stage: str,
        status: str,
        message: str,
        source: str = "",
    ) -> None:
        """发送适度的公开阶段事件，不暴露模型隐藏思维链。"""

        if context.event_sink is None:
            return
        try:
            context.event_sink(StreamEvent(
                event="note_pipeline_progress",
                run_id=context.run_id,
                agent="note",
                data={
                    "stage": stage,
                    "status": status,
                    "source": source,
                    "message": message,
                },
            ))
        except Exception:
            return

    def _acquire_with_retry(
        self, source: str, context: ToolExecutionContext,
    ) -> ToolResult:
        """仅对普通临时异常做有限重试，权限和 Cookie 错误立即抛出。"""

        last_error: Exception | None = None
        for attempt in range(1, self._acquire_attempts + 1):
            try:
                return self._resources.acquire({"source": source}, context)
            except Exception as error:
                last_error = error
                message = str(error).casefold()
                if any(marker in message for marker in (
                    "cookie", "login required", "private video", "权限", "禁止",
                )):
                    raise
                if attempt < self._acquire_attempts:
                    sleep(float(attempt))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _quality_metrics(content: Any, warnings: tuple[str, ...]) -> ContentQualityMetrics:
        data = dict(content) if isinstance(content, Mapping) else {}
        text = str(data.get("text") or "")
        audio = list(data.get("audio_transcript") or ())
        visual = list(data.get("visual_transcript") or ())
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        duplicate_ratio = 0.0 if not lines else 1.0 - len(set(lines)) / len(lines)
        suspicious = sum(text.count(mark) for mark in ("�", "锟", "□"))
        suspicious_ratio = suspicious / max(len(text), 1)
        return ContentQualityMetrics(
            text_characters=len(text.strip()),
            audio_segments=len(audio),
            visual_segments=len(visual),
            duplicate_ratio=round(duplicate_ratio, 4),
            suspicious_character_ratio=round(suspicious_ratio, 4),
            has_warnings=bool(warnings),
        )

    @staticmethod
    def _metrics_dict(metrics: ContentQualityMetrics) -> dict[str, Any]:
        return {
            "text_characters": metrics.text_characters,
            "audio_segments": metrics.audio_segments,
            "visual_segments": metrics.visual_segments,
            "duplicate_ratio": metrics.duplicate_ratio,
            "suspicious_character_ratio": metrics.suspicious_character_ratio,
            "has_warnings": metrics.has_warnings,
        }

    def _save_cache(self, source: str, state: dict[str, Any]) -> None:
        with self._cache_lock:
            self._stage_cache[source] = dict(state)

    @staticmethod
    def _current_stage(state: Mapping[str, Any]) -> str:
        if not state.get("acquired_artifact_id"):
            return "acquire"
        if not state.get("extracted_artifact_id"):
            return "extract"
        if state.get("normalization_status") not in ("completed", "skipped"):
            return "normalize"
        return "build_note"

    @staticmethod
    def _is_retryable_failure(stage: str, error: Exception) -> bool:
        """Only transient failures may return to the Agent Loop."""

        message = str(error).casefold()
        terminal_markers = (
            "fresh cookies", "login required", "private video", "permission",
            "unsupported", "not supported", "不存在", "不支持", "禁止",
        )
        if any(marker in message for marker in terminal_markers):
            return False
        if stage == "extract" and any(marker in message for marker in (
            "mkl_malloc", "allocate memory", "out of memory", "memoryerror",
            "timeout", "temporarily unavailable",
        )):
            return True
        if stage == "normalize" and any(marker in message for marker in (
            "结构化输出", "无法解析", "timeout", "temporarily unavailable",
        )):
            return True
        return stage == "acquire" and any(marker in message for marker in (
            "timeout", "connection", "ssl", "eof", "temporarily unavailable",
        ))

    @staticmethod
    def _failed_item(
        source: str,
        stage: str,
        error: Exception,
        *,
        retryable: bool = False,
        attempt: int = 0,
        max_attempts: int = 1,
    ) -> dict[str, Any]:
        safe_error = LearningNotePipelineTools._safe_error(error)
        return {
            "source": source,
            "status": "failed",
            "failed_stage": stage,
            "error": safe_error,
            "cache_hit": False,
            "retryable": retryable,
            "terminal": not retryable,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "next_strategy": (
                "retry_same_extraction"
                if retryable and stage == "extract"
                else "retry_smaller_normalization"
                if retryable and stage == "normalize"
                else ""
            ),
        }

    @staticmethod
    def _safe_error(error: Exception) -> str:
        """Keep user-facing failure context useful without leaking giant model output."""

        raw = str(error).strip()
        lowered = raw.casefold()
        if "invalid json output" in lowered or "结构化输出" in raw:
            return "LLM 结构化输出不完整或无法解析，请缩小单次处理内容后重试"
        first_line = next((line.strip() for line in raw.splitlines() if line.strip()), "")
        if not first_line:
            return type(error).__name__
        return first_line[:500] + ("…" if len(first_line) > 500 else "")

    @staticmethod
    def _result_from_items(items: list[dict[str, Any]]) -> ToolResult:
        completed = [item for item in items if item.get("status") == "completed"]
        failed = [item for item in items if item.get("status") != "completed"]
        retryable_failed = [item for item in failed if item.get("retryable") is True]
        terminal = bool(failed) and not retryable_failed
        artifact_ids = tuple(
            artifact_id
            for item in completed
            for artifact_id in (
                item.get("bundle_artifact_id"),
                *(item.get("note_artifact_ids") or ()),
            )
            if artifact_id
        )
        answer_parts = [
            f"已完成 {len(completed)}/{len(items)} 个资源的学习笔记生成。"
        ]
        for index, item in enumerate(completed, start=1):
            topics = "、".join(item.get("core_topics") or ()) or "详见笔记正文"
            answer_parts.extend((
                "",
                f"### {index}. {item.get('title') or item.get('source_name') or '学习笔记'}",
                f"- 内容概述：{item.get('introduction') or '已按来源完整整理'}",
                f"- 核心要点：{topics}",
            ))
        if failed:
            answer_parts.extend(("", "### 未完成的资源"))
            answer_parts.extend(
                f"- {item['source']}：{item.get('error', '处理失败')}" for item in failed
            )
        final_answer_hint = "\n".join(answer_parts)
        return ToolResult(
            summary=(
                f"笔记批次处理完成：成功 {len(completed)}/{len(items)} 个来源；"
                "结果包含各来源内容简介和核心知识点，可直接生成最终汇总回答。"
            ),
            payload={
                "items": items,
                "success_count": len(completed),
                "failure_count": len(failed),
                "total_count": len(items),
                "completed_item": not failed,
                "task_completed": bool(completed) and not failed,
                "retryable": bool(retryable_failed),
                "retry_strategy": "retry_same_extraction" if retryable_failed else "",
                "task_terminal": terminal,
                "final_answer_hint": final_answer_hint,
                "source_identities": [item["source"] for item in completed],
            },
            artifact_ids=artifact_ids,
            warnings=tuple(
                f"{item['source']}：{item.get('error', '处理失败')}" for item in failed
            ),
            partial=bool(failed),
            retryable=bool(retryable_failed),
        )

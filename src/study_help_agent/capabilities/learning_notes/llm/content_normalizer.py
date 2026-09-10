"""高噪声文本和视频双文本的 LLM 标准化操作。

该能力仅供 Agent 按需调用。长内容按段落切批处理，每批都强调“去噪而非摘要”，最终
拼接为可直接交给 build_learning_note 的 CleanContent。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from study_help_agent.observability.context import map_with_trace

from study_help_agent.capabilities.learning_notes.domain import (
    ExtractedContent,
    NormalizedContent,
    TranscriptSegment,
)
from study_help_agent.infrastructure.llm.local_structured_output import (
    LocalStructuredOutput,
)

from .schemas import CleanContentOutput


class LearningContentNormalizerOperations:
    """执行深度文本去噪、音画对齐融合和分批结果合并。"""

    MAX_BATCH_CHARACTERS = 8_000
    VIDEO_BATCH_CHARACTERS = 3_000
    VIDEO_WINDOW_SECONDS = 480
    MIN_RETRY_CHARACTERS = 700
    MAX_SPLIT_RETRIES = 3
    MAX_BATCHES = 100

    def __init__(
        self,
        llm,
        *,
        max_batch_characters: int = MAX_BATCH_CHARACTERS,
        max_parallelism: int = 3,
    ) -> None:
        self._normalizer = LocalStructuredOutput(llm, CleanContentOutput)
        self._max_batch_characters = max(2_000, max_batch_characters)
        self._max_parallelism = max(1, max_parallelism)

    def normalize(self, content: ExtractedContent) -> NormalizedContent:
        """把纯文本或视频双文本转换为语义连贯且尽量完整的干净正文。"""

        batches, mode = self._prepare_batches(content)
        if not batches:
            raise ValueError("提取结果中没有可标准化的文本")
        if len(batches) > self.MAX_BATCHES:
            raise ValueError("标准化内容过长，请先按章节或视频时间范围拆分")
        outputs = self._normalize_batches(batches=batches, mode=mode)
        cleaned = "\n\n".join(
            output.cleaned_text.strip() for output in outputs if output.cleaned_text.strip()
        )
        if not cleaned:
            raise ValueError("内容标准化后没有有效文本")
        notes = list(
            dict.fromkeys(
                note
                for output in outputs
                for note in output.processing_notes
                if note.strip()
            )
        )
        metadata = {
            **content.metadata,
            "normalization_mode": mode,
            "normalization_batches": len(batches),
            "normalization_output_batches": len(outputs),
            "video_window_seconds": (
                self.VIDEO_WINDOW_SECONDS if mode == "video_fusion" else None
            ),
        }
        return NormalizedContent(
            cleaned_text=cleaned,
            processing_notes=notes,
            metadata=metadata,
            warnings=list(content.warnings),
        )

    def _normalize_batches(
        self, *, batches: list[str], mode: str
    ) -> list[CleanContentOutput]:
        """Normalize independent chunks concurrently and preserve source order."""

        def run(index_and_batch: tuple[int, str]) -> list[CleanContentOutput]:
            index, batch = index_and_batch
            try:
                return self._normalize_batch_resilient(batch=batch, mode=mode)
            except Exception as error:
                raise TimeoutError(
                    f"内容标准化第 {index + 1}/{len(batches)} 个分块失败："
                    "LLM 结构化输出在自适应缩小分块后仍无法解析"
                ) from error

        indexed = list(enumerate(batches))
        max_parallelism = getattr(self, "_max_parallelism", 1)
        if len(indexed) == 1 or max_parallelism == 1:
            grouped = [run(item) for item in indexed]
            return [output for group in grouped for output in group]
        with ThreadPoolExecutor(
            max_workers=min(max_parallelism, len(indexed)),
            thread_name_prefix="content-normalizer",
        ) as executor:
            grouped = map_with_trace(executor, run, indexed)
        return [output for group in grouped for output in group]

    def _normalize_batch_resilient(
        self, *, batch: str, mode: str, depth: int = 0
    ) -> list[CleanContentOutput]:
        """只在当前分块失败时递归缩小，避免重做其他已成功分块。"""

        try:
            return [self._normalize_batch(batch=batch, mode=mode)]
        except Exception:
            if depth >= self.MAX_SPLIT_RETRIES or len(batch) <= self.MIN_RETRY_CHARACTERS:
                raise
            limit = max(self.MIN_RETRY_CHARACTERS, len(batch) // 2)
            smaller = self._split_batches(batch, max_characters=limit)
            if len(smaller) <= 1:
                raise
            outputs: list[CleanContentOutput] = []
            for item in smaller:
                outputs.extend(
                    self._normalize_batch_resilient(
                        batch=item,
                        mode=mode,
                        depth=depth + 1,
                    )
                )
            return outputs

    def _normalize_batch(self, *, batch: str, mode: str) -> CleanContentOutput:
        """根据文本来源选择普通深清洗或视频音画融合提示词。"""

        if mode == "video_fusion":
            instruction = (
                "融合以下带时间戳的音频文本与画面文字。音频负责讲解主线，画面文字补充"
                "代码、公式、标题、步骤和音频没有念出的细节；重复信息只保留一次。删除口癖、"
                "识别乱码和广告。这个步骤是转写整理，不是总结：不得概括、缩写、提炼或压缩"
                "有效内容；每段独立解释、示例、论证、步骤、条件、例外、代码和画面信息都要"
                "保留。只能删除可确认的重复和噪声，不能因为语义相近就合并不同细节。整理成"
                "语义连续的纯净正文，并保留能帮助定位内容的关键时间戳。输出信息量应与输入"
                "有效信息量基本相当。"
            )
        else:
            instruction = (
                "深度清洗以下高噪声文本：删除广告、导航、口癖、OCR乱码和无意义重复，修复"
                "断句与明显识别错误。不得总结，不得删除事实、示例、数据、代码、限制条件和"
                "有效解释；原有结构良好时尽量保留。"
            )
        return self._normalizer.invoke(f"{instruction}\n\n待处理内容：\n{batch}")

    @staticmethod
    def _timestamp(seconds: float) -> str:
        minutes, remainder = divmod(max(seconds, 0.0), 60)
        return f"{int(minutes):02d}:{remainder:05.2f}"

    @classmethod
    def _segment_line(cls, kind: str, segment: TranscriptSegment) -> str:
        return (
            f"[{cls._timestamp(segment.start_seconds)}-"
            f"{cls._timestamp(segment.end_seconds)}][{kind}] {segment.text}"
        )

    @classmethod
    def _source_text(cls, content: ExtractedContent) -> tuple[str, str]:
        """按时间排序视频双文本；普通资源直接使用正文。"""

        if content.audio_transcript or content.visual_transcript:
            events = [
                (item.start_seconds, cls._segment_line("音频", item))
                for item in content.audio_transcript
            ] + [
                (item.start_seconds, cls._segment_line("画面", item))
                for item in content.visual_transcript
            ]
            events.sort(key=lambda item: item[0])
            return "\n".join(line for _, line in events), "video_fusion"
        return content.text, "deep_clean"

    def _prepare_batches(
        self, content: ExtractedContent
    ) -> tuple[list[str], str]:
        """普通文本按字符切分；视频先按时间窗对齐，再限制单次字符量。"""

        if content.audio_transcript or content.visual_transcript:
            events = [
                (item.start_seconds, self._segment_line("音频", item))
                for item in content.audio_transcript
            ] + [
                (item.start_seconds, self._segment_line("画面", item))
                for item in content.visual_transcript
            ]
            events.sort(key=lambda item: item[0])
            windows: dict[int, list[str]] = {}
            for timestamp, line in events:
                window = int(max(timestamp, 0.0) // self.VIDEO_WINDOW_SECONDS)
                windows.setdefault(window, []).append(line)
            batches: list[str] = []
            for window in sorted(windows):
                batches.extend(self._split_batches(
                    "\n".join(windows[window]),
                    max_characters=min(
                        self.VIDEO_BATCH_CHARACTERS,
                        getattr(self, "_max_batch_characters", self.MAX_BATCH_CHARACTERS),
                    ),
                ))
            return [item for item in batches if item.strip()], "video_fusion"

        source = content.text.strip()
        if not source:
            return [], "deep_clean"
        return self._split_batches(
            source,
            max_characters=getattr(
                self, "_max_batch_characters", self.MAX_BATCH_CHARACTERS
            ),
        ), "deep_clean"

    @classmethod
    def _split_batches(
        cls, text: str, *, max_characters: int | None = None
    ) -> list[str]:
        """尽量在段落边界切分，避免粗暴截断句子。"""

        limit = max_characters or cls.MAX_BATCH_CHARACTERS
        # Video transcripts usually contain one timestamped event per line and no
        # blank paragraphs, so line boundaries must also be valid split points.
        paragraphs = text.replace("\r\n", "\n").split("\n")
        batches: list[str] = []
        current: list[str] = []
        size = 0
        for paragraph in paragraphs:
            if len(paragraph) > limit:
                if current:
                    batches.append("\n".join(current))
                    current, size = [], 0
                batches.extend(
                    paragraph[index:index + limit]
                    for index in range(0, len(paragraph), limit)
                )
                continue
            addition = len(paragraph) + (1 if current else 0)
            if current and size + addition > limit:
                batches.append("\n".join(current))
                current, size = [], 0
            current.append(paragraph)
            size += addition
        if current:
            batches.append("\n".join(current))
        return batches

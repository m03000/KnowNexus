"""文本文档、PDF、Word、图片、音频和视频的内容提取适配器。

普通格式使用轻量解析；扫描件使用 OCR；视频分别生成带时间戳的音频文本和画面文本。
重型依赖全部延迟导入，只有真实处理对应资源时才产生启动和模型加载成本。
"""

from __future__ import annotations

import gc
import html
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any
import re

from study_help_agent.capabilities.learning_notes.domain import (
    AcquiredResource,
    ExtractedContent,
    TranscriptSegment,
)
from study_help_agent.observability.context import submit_with_trace

for _thread_env in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_thread_env, "1")


def _configure_tesseract(pytesseract: Any) -> None:
    """Point pytesseract at the OCR engine bundled by the portable build."""

    command = os.getenv("TESSERACT_CMD", "").strip()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command


class MultiFormatLearningContentExtractor:
    """按文件扩展名路由到确定性的格式提取实现。"""

    TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".log", ".py", ".json"}
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
    AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
    VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv"}

    def __init__(
        self,
        *,
        whisper_model: str = "small",
        whisper_device: str = "auto",
        whisper_compute_type: str = "auto",
        video_sample_seconds: int = 15,
        video_max_frames: int = 120,
        ocr_languages: str = "chi_sim+eng",
        media_max_parallelism: int = 1,
        video_split_threshold_seconds: int = 600,
        video_segment_seconds: int = 480,
        parallel_audio_visual: bool = True,
    ) -> None:
        self._whisper_model = whisper_model
        self._whisper_device = whisper_device.strip().lower() or "auto"
        self._whisper_compute_type = whisper_compute_type.strip().lower() or "auto"
        self._resolved_whisper_device = ""
        self._video_sample_seconds = max(video_sample_seconds, 1)
        self._video_max_frames = max(video_max_frames, 1)
        self._ocr_languages = ocr_languages
        self._media_semaphore = BoundedSemaphore(max(media_max_parallelism, 1))
        self._video_split_threshold_seconds = max(video_split_threshold_seconds, 1)
        self._video_segment_seconds = max(video_segment_seconds, 1)
        self._parallel_audio_visual = parallel_audio_visual

    def extract(
        self,
        resource: AcquiredResource,
        *,
        progress: Callable[[str, str], None] | None = None,
    ) -> ExtractedContent:
        """选择格式提取器并统一补充来源元数据。"""

        path = Path(resource.local_path).resolve(strict=True)
        suffix = path.suffix.lower()
        if suffix in self.TEXT_SUFFIXES:
            text = self._read_text(path)
            return self._result(resource, text=text, extraction_mode="text")
        if suffix in {".html", ".htm"}:
            return self._result(
                resource, text=self._extract_html(path), extraction_mode="html"
            )
        if suffix == ".docx":
            return self._result(
                resource, text=self._extract_docx(path), extraction_mode="docx"
            )
        if suffix == ".pdf":
            text, warnings = self._extract_pdf(path)
            return self._result(
                resource, text=text, extraction_mode="pdf", warnings=warnings
            )
        if suffix in self.IMAGE_SUFFIXES:
            return self._result(
                resource, text=self._ocr_image(path), extraction_mode="image_ocr"
            )
        if suffix in self.AUDIO_SUFFIXES:
            with self._media_semaphore:
                audio = self._transcribe_audio(path)
            return self._result(
                resource, audio=audio, extraction_mode="audio_transcript"
            )
        if suffix in self.VIDEO_SUFFIXES:
            with self._media_semaphore:
                audio, visual, processing_metadata = self._extract_video(
                    resource, path, progress=progress
                )
            return self._result(
                resource,
                audio=audio,
                visual=visual,
                extraction_mode="video_dual_transcript",
                processing_metadata=processing_metadata,
            )
        raise ValueError(f"暂不支持的学习资源格式：{suffix or path.name}")

    @staticmethod
    def _read_text(path: Path) -> str:
        """按常见中文编码读取文本，并格式化 JSON。"""

        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise UnicodeError(f"无法识别文本编码：{path.name}")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if path.suffix.lower() == ".json":
            try:
                return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        return text.strip()

    @staticmethod
    def _extract_html(path: Path) -> str:
        """移除脚本、样式和导航噪声，并保留主要标题层级。"""

        try:
            from bs4 import BeautifulSoup
        except ImportError as error:
            raise RuntimeError(
                "HTML 提取需要安装：pip install -e .[learning-documents]"
            ) from error
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        for element in soup(["script", "style", "noscript", "nav", "footer"]):
            element.decompose()
        parts: list[str] = []
        for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            if element.name and element.name.startswith("h"):
                parts.append(f"{'#' * int(element.name[1])} {text}")
            elif element.name == "li":
                parts.append(f"- {text}")
            elif element.name == "pre":
                parts.append(f"```\n{text}\n```")
            else:
                parts.append(text)
        return "\n\n".join(parts)

    @staticmethod
    def _extract_docx(path: Path) -> str:
        """读取 Word 段落标题和表格，转换成 Markdown。"""

        try:
            from docx import Document
            from docx.table import Table
        except ImportError as error:
            raise RuntimeError(
                "Word 提取需要安装：pip install -e .[learning-documents]"
            ) from error
        document = Document(str(path))
        parts: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                rows = [
                    [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    for row in block.rows
                ]
                if rows:
                    parts.append("| " + " | ".join(rows[0]) + " |")
                    parts.append(
                        "| " + " | ".join("---" for _ in rows[0]) + " |"
                    )
                    parts.extend(
                        "| " + " | ".join(row) + " |" for row in rows[1:]
                    )
                continue
            paragraph = block
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style else "").lower()
            if style.startswith("heading"):
                digits = "".join(char for char in style if char.isdigit())
                level = min(max(int(digits or "1"), 1), 6)
                parts.append(f"{'#' * level} {text}")
            else:
                parts.append(text)
        return "\n\n".join(parts)

    def _extract_pdf(self, path: Path) -> tuple[str, list[str]]:
        """先提取 PDF 文本；疑似扫描页再按页 OCR。"""

        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError(
                "PDF 提取需要安装：pip install -e .[learning-documents]"
            ) from error
        reader = PdfReader(str(path))
        pages: list[str] = []
        scanned_indexes: list[int] = []
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if len(text) < 30:
                scanned_indexes.append(index)
            pages.append(text)
        warnings: list[str] = []
        if scanned_indexes:
            try:
                ocr_pages = self._ocr_pdf_pages(path, scanned_indexes)
                for index, text in ocr_pages.items():
                    if len(text) > len(pages[index]):
                        pages[index] = text
            except RuntimeError as error:
                warnings.append(str(error))
        rendered = [f"## 第 {index + 1} 页\n\n{text}" for index, text in enumerate(pages) if text]
        if not rendered:
            raise ValueError("PDF 未提取到文本；请安装 OCR 依赖并配置中文语言包")
        return "\n\n".join(rendered), warnings

    def _ocr_pdf_pages(self, path: Path, indexes: list[int]) -> dict[int, str]:
        """使用 PyMuPDF 渲染扫描页，再交给 Tesseract OCR。"""

        try:
            import fitz
            import pytesseract
            from PIL import Image
        except ImportError as error:
            raise RuntimeError(
                "扫描 PDF OCR 需要安装 learning-documents 可选依赖和 Tesseract 程序"
            ) from error
        _configure_tesseract(pytesseract)
        result: dict[int, str] = {}
        with fitz.open(str(path)) as document:
            for index in indexes:
                pixmap = document[index].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                result[index] = pytesseract.image_to_string(
                    image, lang=self._ocr_languages, timeout=120
                ).strip()
        return result

    def _ocr_image(self, path: Path) -> str:
        """使用 Tesseract 对图片或扫描件执行 OCR。"""

        try:
            import pytesseract
            from PIL import Image
        except ImportError as error:
            raise RuntimeError(
                "图片 OCR 需要安装 learning-documents 可选依赖和 Tesseract 程序"
            ) from error
        _configure_tesseract(pytesseract)
        text = pytesseract.image_to_string(
            Image.open(path), lang=self._ocr_languages, timeout=120
        ).strip()
        if not text:
            raise ValueError("图片 OCR 没有识别到有效文字")
        return text

    def _create_whisper_model(self) -> Any:
        """优先在 CUDA 创建模型；CUDA 环境不完整时仅回退一次到 CPU。"""

        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "音视频转写需要安装：pip install -e .[learning-media]"
            ) from error
        requested = self._whisper_device
        if requested == "auto":
            try:
                import ctranslate2
                requested = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except (ImportError, RuntimeError):
                requested = "cpu"
        compute_type = self._whisper_compute_type
        if compute_type == "auto":
            compute_type = "float16" if requested == "cuda" else "int8"
        try:
            model = WhisperModel(
                self._whisper_model, device=requested, compute_type=compute_type
            )
            self._resolved_whisper_device = requested
            return model
        except RuntimeError:
            if requested != "cuda" or self._whisper_device == "cuda":
                raise
            self._resolved_whisper_device = "cpu"
            return WhisperModel(self._whisper_model, device="cpu", compute_type="int8")

    def _transcribe_audio(
        self,
        path: Path,
        *,
        model: Any | None = None,
        time_offset: float = 0.0,
    ) -> list[TranscriptSegment]:
        """使用 faster-whisper 生成带时间戳的语音文本。"""

        owns_model = model is None
        active_model = model or self._create_whisper_model()
        try:
            segments, _ = active_model.transcribe(str(path), vad_filter=True)
            return [
                TranscriptSegment(
                    start_seconds=time_offset + float(segment.start),
                    end_seconds=time_offset + float(segment.end),
                    text=str(segment.text).strip(),
                )
                for segment in segments
                if str(segment.text).strip()
            ]
        finally:
            if owns_model:
                del active_model
                gc.collect()

    def _extract_video(
        self,
        resource: AcquiredResource,
        path: Path,
        *,
        progress: Callable[[str, str], None] | None = None,
    ) -> tuple[list[TranscriptSegment], list[TranscriptSegment], dict[str, Any]]:
        """Route short and long videos to isolated extraction strategies."""

        emit = progress or (lambda _stage, _message: None)
        subtitles = self._extract_subtitles(resource, path)
        if subtitles:
            emit("subtitle_video", f"已读取平台字幕 {len(subtitles)} 段，将跳过 Whisper 转写")
        emit("inspect_video", "正在读取视频时长并判断是否需要切片")
        duration = self._video_duration(path)
        if not self._should_segment_video(duration):
            return self._extract_short_video(
                path, duration=duration, subtitles=subtitles, progress=progress
            )
        return self._extract_long_video(
            path, duration=duration, subtitles=subtitles, progress=progress
        )

    @classmethod
    def _extract_subtitles(
        cls, resource: AcquiredResource, media_path: Path
    ) -> list[TranscriptSegment]:
        """读取 yt-dlp 保存的 VTT/SRT 字幕，并转成统一时间戳片段。"""

        configured = resource.metadata.get("subtitle_paths", [])
        paths = [Path(str(item)) for item in configured] if isinstance(configured, list) else []
        if not paths:
            paths = [
                item for item in media_path.parent.iterdir()
                if item.is_file() and item.suffix.lower() in {".vtt", ".srt"}
            ]
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".vtt", ".srt"}:
                continue
            segments = cls._parse_subtitle(path)
            if segments:
                return segments
        return []

    @staticmethod
    def _parse_subtitle(path: Path) -> list[TranscriptSegment]:
        """解析常见 VTT/SRT cue，去除标签并过滤连续重复字幕。"""

        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        timing = re.compile(
            r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+"
            r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})"
        )

        def seconds(value: str) -> float:
            parts = value.replace(",", ".").split(":")
            if len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

        result: list[TranscriptSegment] = []
        blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
        previous = ""
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            match = next((timing.search(line) for line in lines if timing.search(line)), None)
            if not match:
                continue
            text_lines = [line for line in lines if "-->" not in line and not line.isdigit()]
            text = " ".join(text_lines)
            text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
            if not text or text == previous:
                continue
            result.append(TranscriptSegment(
                start_seconds=seconds(match.group("start")),
                end_seconds=seconds(match.group("end")),
                text=text,
            ))
            previous = text
        return result

    def _extract_short_video(
        self,
        path: Path,
        *,
        duration: float,
        subtitles: list[TranscriptSegment] | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> tuple[list[TranscriptSegment], list[TranscriptSegment], dict[str, Any]]:
        """Preserve direct short-video extraction, with only two-lane concurrency."""

        emit = progress or (lambda _stage, _message: None)

        def transcribe() -> list[TranscriptSegment]:
            if subtitles:
                return subtitles
            emit("load_whisper", "普通视频：正在加载 Whisper 模型")
            result = self._transcribe_audio(path)
            emit("transcribe_video", "普通视频：音频转写完成")
            return result

        def extract_visuals() -> list[TranscriptSegment]:
            emit("ocr_video", "普通视频：正在提取画面文字")
            result = self._extract_video_frames(path)
            emit("ocr_video", "普通视频：画面文字提取完成")
            return result

        if self._parallel_audio_visual:
            emit("parallel_media", "普通视频：正在并行执行音频转写与画面 OCR")
            with ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="short-video"
            ) as executor:
                audio_future = submit_with_trace(executor, transcribe)
                visual_future = submit_with_trace(executor, extract_visuals)
                audio = audio_future.result()
                visual = visual_future.result()
        else:
            audio = transcribe()
            visual = extract_visuals()
        emit("release_media", "普通视频处理资源已释放")
        return audio, visual, {
            "video_duration_seconds": round(duration, 3),
            "video_segmented": False,
            "video_segment_count": 1,
            "audio_visual_parallel": self._parallel_audio_visual,
            "video_processing_strategy": "short_video_direct",
            "transcript_source": "subtitle" if subtitles else "whisper",
            "whisper_device": "not_used" if subtitles else self._resolved_whisper_device,
        }

    def _extract_long_video(
        self,
        path: Path,
        *,
        duration: float,
        subtitles: list[TranscriptSegment] | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> tuple[list[TranscriptSegment], list[TranscriptSegment], dict[str, Any]]:
        """Split only long videos; each audio/OCR lane remains internally serial."""

        emit = progress or (lambda _stage, _message: None)

        emit("split_video", "视频超过 10 分钟，正在按约 8 分钟切片")
        with tempfile.TemporaryDirectory(
            prefix="study-video-segments-", dir=str(path.parent)
        ) as temporary_directory:
            segment_paths = self._split_video(
                path, Path(temporary_directory), self._video_segment_seconds
            )
            emit("split_video", f"视频切片完成，共 {len(segment_paths)} 个分片")
            segment_durations = [self._video_duration(item) for item in segment_paths]

            def transcribe_segments() -> list[TranscriptSegment]:
                if subtitles:
                    return subtitles
                audio: list[TranscriptSegment] = []
                offset = 0.0
                emit("load_whisper", "长视频：正在加载一个共享 Whisper 模型")
                model = self._create_whisper_model()
                try:
                    for index, (segment_path, segment_duration) in enumerate(
                        zip(segment_paths, segment_durations), start=1
                    ):
                        emit(
                            "transcribe_segment",
                            f"长视频：正在转写第 {index}/{len(segment_paths)} 个分片",
                        )
                        audio.extend(
                            self._transcribe_audio(
                                segment_path, model=model, time_offset=offset
                            )
                        )
                        offset += segment_duration
                    return audio
                finally:
                    del model
                    gc.collect()
                    emit("release_whisper", "长视频：Whisper 模型已释放")

            def extract_visual_segments() -> list[TranscriptSegment]:
                visual: list[TranscriptSegment] = []
                offset = 0.0
                remaining_frames = self._video_max_frames
                for index, (segment_path, segment_duration) in enumerate(
                    zip(segment_paths, segment_durations), start=1
                ):
                    if remaining_frames > 0:
                        emit(
                            "ocr_segment",
                            f"长视频：正在提取第 {index}/{len(segment_paths)} 个分片的画面文字",
                        )
                        frames = self._extract_video_frames(
                            segment_path,
                            time_offset=offset,
                            max_frames=remaining_frames,
                        )
                        visual.extend(frames)
                        remaining_frames -= len(frames)
                    offset += segment_duration
                return visual

            if self._parallel_audio_visual:
                emit("parallel_media", "长视频：音频分片路线与画面 OCR 路线并行执行")
                with ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="long-video"
                ) as executor:
                    audio_future = submit_with_trace(executor, transcribe_segments)
                    visual_future = submit_with_trace(executor, extract_visual_segments)
                    audio = audio_future.result()
                    visual = visual_future.result()
            else:
                audio = transcribe_segments()
                visual = extract_visual_segments()
            emit("release_media", "长视频分片和临时资源已释放")
            return audio, visual, {
                "video_duration_seconds": round(duration, 3),
                "video_segmented": True,
                "video_segment_count": len(segment_paths),
                "video_segment_seconds": self._video_segment_seconds,
                "audio_visual_parallel": self._parallel_audio_visual,
                "video_processing_strategy": "long_video_segmented",
                "transcript_source": "subtitle" if subtitles else "whisper",
                "whisper_device": "not_used" if subtitles else self._resolved_whisper_device,
            }

    def _should_segment_video(self, duration_seconds: float) -> bool:
        """Segment only when duration is strictly greater than the threshold."""

        return duration_seconds > self._video_split_threshold_seconds

    @staticmethod
    def _video_duration(path: Path) -> float:
        """Read duration without loading the complete video into memory."""

        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("读取视频时长需要安装 learning-media 依赖") from error
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError(f"无法打开视频文件：{path.name}")
        try:
            fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
            frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            return float(frame_count / fps) if frame_count else 0.0
        finally:
            capture.release()

    @staticmethod
    def _split_video(path: Path, output_directory: Path, seconds: int) -> list[Path]:
        """Use FFmpeg stream copy so segmentation does not re-encode the video."""

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("长视频切片需要 FFmpeg，并确保 ffmpeg 已加入 PATH")
        output_pattern = output_directory / "segment_%03d.mkv"
        process = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(path), "-map", "0:v:0", "-map", "0:a?",
                "-c", "copy", "-f", "segment", "-segment_time", str(seconds),
                "-reset_timestamps", "1", str(output_pattern),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        segments = sorted(output_directory.glob("segment_*.mkv"))
        if process.returncode != 0 or not segments:
            detail = process.stderr.strip() or "FFmpeg 未生成任何视频分片"
            raise RuntimeError(f"长视频切片失败：{detail}")
        return segments

    def _extract_video_frames(
        self,
        path: Path,
        *,
        time_offset: float = 0.0,
        max_frames: int | None = None,
    ) -> list[TranscriptSegment]:
        """按固定时间间隔抽取关键帧，并对画面文字执行 OCR。"""

        try:
            import cv2
            import pytesseract
        except ImportError as error:
            raise RuntimeError(
                "视频画面文字提取需要安装 learning-media、learning-documents 和 Tesseract"
            ) from error
        _configure_tesseract(pytesseract)
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError(f"无法打开视频文件：{path.name}")
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = frame_count / fps if frame_count else 0
        result: list[TranscriptSegment] = []
        frame_limit = self._video_max_frames if max_frames is None else max(max_frames, 0)
        previous = ""
        timestamp = 0.0
        try:
            while timestamp <= duration and len(result) < frame_limit:
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ok, frame = capture.read()
                if not ok:
                    break
                text = pytesseract.image_to_string(
                    frame, lang=self._ocr_languages, timeout=30
                ).strip()
                if text and text != previous:
                    result.append(
                        TranscriptSegment(
                            start_seconds=time_offset + timestamp,
                            end_seconds=time_offset + min(
                                timestamp + self._video_sample_seconds, duration
                            ),
                            text=text,
                        )
                    )
                    previous = text
                timestamp += self._video_sample_seconds
        finally:
            capture.release()
        return result

    @staticmethod
    def _result(
        resource: AcquiredResource,
        *,
        text: str = "",
        audio: list[TranscriptSegment] | None = None,
        visual: list[TranscriptSegment] | None = None,
        extraction_mode: str,
        warnings: list[str] | None = None,
        processing_metadata: dict[str, Any] | None = None,
    ) -> ExtractedContent:
        """创建统一提取结果并带回来源信息。"""

        return ExtractedContent(
            resource_id=resource.resource_id,
            text=text.strip(),
            audio_transcript=audio or [],
            visual_transcript=visual or [],
            metadata={
                "resource_id": resource.resource_id,
                "source_uri": resource.source_uri,
                "source_type": resource.source_type,
                "source_name": resource.file_name,
                "managed_source_path": resource.local_path,
                "media_type": resource.media_type,
                "extraction_mode": extraction_mode,
                **(processing_metadata or {}),
            },
            warnings=warnings or [],
        )

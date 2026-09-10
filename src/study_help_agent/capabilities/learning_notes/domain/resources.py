"""学习笔记前置资源处理使用的稳定领域模型。

这些对象只表达“已经获取的资源、已经提取的内容和已经标准化的文本”，不依赖下载、
OCR、语音识别或 LLM 的具体实现，便于工具之间通过 Artifact 传递。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AcquiredResource:
    """已经复制或下载到受控运行目录中的原始资源。"""

    resource_id: str
    local_path: str
    source_uri: str
    source_type: str
    media_type: str
    file_name: str
    size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """带起止时间的音频转写或画面文字片段。"""

    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedContent:
    """不同资源提取器输出的统一内容形式。"""

    resource_id: str
    text: str = ""
    audio_transcript: list[TranscriptSegment] = field(default_factory=list)
    visual_transcript: list[TranscriptSegment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NormalizedContent:
    """深度去噪或多模态融合后可直接进入笔记构建的正文。"""

    cleaned_text: str
    processing_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

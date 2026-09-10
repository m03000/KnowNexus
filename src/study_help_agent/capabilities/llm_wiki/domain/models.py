"""LLM Wiki 来源层领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WikiSourceDraft:
    """一个可追溯、可重复编译的 Wiki 来源。"""

    source_id: str
    source_kind: str
    source_ref: str
    title: str
    content: str
    original_path: str = ""
    media_type: str = "text/markdown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WikiSourceReceipt:
    """来源快照写入及构建排队结果。"""

    source_id: str
    version: int
    content_hash: str
    normalized_path: str
    queued: bool
    skipped_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "normalized_path": self.normalized_path,
            "queued": self.queued,
            "skipped_reason": self.skipped_reason,
        }

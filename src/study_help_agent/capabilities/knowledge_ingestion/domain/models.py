"""自动入库的稳定领域数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping

from .enums import IngestionStatus, KnowledgeAssetType, KnowledgeSpace


def utc_now() -> datetime:
    """返回带时区的 UTC 时间，避免服务器时区改变造成排序错误。"""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class KnowledgeAssetDraft:
    """Projector 输出的待持久化知识资产。"""

    space: KnowledgeSpace
    asset_type: KnowledgeAssetType
    stable_source_key: str
    title: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.stable_source_key.strip():
            raise ValueError("stable_source_key cannot be empty")
        if not self.title.strip():
            raise ValueError("Knowledge asset title cannot be empty")
        if not self.content.strip():
            raise ValueError("Knowledge asset content cannot be empty")


@dataclass(frozen=True, slots=True)
class KnowledgeAsset:
    """已经分配稳定 ID、哈希和版本号的规范知识资产。"""

    asset_id: str
    space: KnowledgeSpace
    asset_type: KnowledgeAssetType
    stable_source_key: str
    title: str
    content: str
    content_hash: str
    version: int
    status: IngestionStatus
    metadata: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionJob:
    """Outbox 中等待后续切块和索引的可靠任务。"""

    job_id: str
    asset_id: str
    asset_version: int
    event_type: str = "knowledge_asset.ready"
    status: IngestionStatus = IngestionStatus.PENDING
    attempt_count: int = 0
    next_retry_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionReceipt:
    """同步捕获阶段返回给 Runtime 的轻量结果。"""

    asset_id: str
    job_id: str | None
    created: bool
    skipped_reason: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """由规范资产切出的可检索最小单元，保留来源与标题路径。"""

    chunk_id: str
    asset_id: str
    asset_version: int
    space: KnowledgeSpace
    chunk_index: int
    logical_key: str
    content: str
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

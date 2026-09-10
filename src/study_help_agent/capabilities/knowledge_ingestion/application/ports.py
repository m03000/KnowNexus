"""定义应用层对事务型知识存储的最小依赖。"""

from collections.abc import Sequence
from typing import Protocol

from ..domain.models import (
    IngestionJob,
    IngestionReceipt,
    KnowledgeAsset,
    KnowledgeAssetDraft,
    KnowledgeChunk,
)


class KnowledgeIngestionRepository(Protocol):
    """以单个事务保存规范资产并创建 Outbox 任务。"""

    def upsert_and_enqueue(self, draft: KnowledgeAssetDraft) -> IngestionReceipt:
        """内容未变化时跳过；变化时递增版本并可靠排队。"""

        ...


class IngestionWorkRepository(Protocol):
    """后台 Worker 领取任务、读资产、保存切块和更新状态所需端口。"""

    def claim_jobs(self, *, limit: int) -> tuple[IngestionJob, ...]: ...

    def get_asset(self, asset_id: str) -> KnowledgeAsset | None: ...

    def replace_chunks(self, asset: KnowledgeAsset, chunks: Sequence[KnowledgeChunk]) -> None: ...

    def mark_completed(self, job_id: str, asset_id: str) -> None: ...

    def mark_superseded(self, job_id: str) -> None: ...

    def mark_failed(self, job_id: str, error: str, *, max_attempts: int) -> None: ...

    def recover_processing_jobs(self) -> int: ...

    def finalize_delete(self, asset_id: str) -> None: ...


class EmbeddingEncoder(Protocol):
    """将文本批量编码成与具体模型库无关的浮点向量。"""

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorIndexWriter(Protocol):
    """按资产原子替换某个知识空间中的向量点。"""

    def replace_asset_chunks(
        self,
        *,
        asset: KnowledgeAsset,
        chunks: Sequence[KnowledgeChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None: ...

    def delete_asset(self, asset: KnowledgeAsset) -> None: ...


class ChunkingStrategy(Protocol):
    """把一个资产转换成带稳定逻辑键的切块候选。"""

    def split(self, asset: KnowledgeAsset): ...

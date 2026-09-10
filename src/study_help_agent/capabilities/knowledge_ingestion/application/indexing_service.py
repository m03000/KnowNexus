"""执行单个 Outbox 任务的切块、向量化和双索引写入用例。"""

from study_help_agent.capabilities.knowledge_ingestion.domain.hashing import (
    content_digest,
    stable_chunk_id,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.models import (
    IngestionJob,
    KnowledgeChunk,
)

from .ports import ChunkingStrategy, EmbeddingEncoder, IngestionWorkRepository, VectorIndexWriter


class KnowledgeIndexingService:
    """把可靠任务处理成规范 Chunk、SQLite FTS5 和 Qdrant 向量点。"""

    def __init__(
        self,
        *,
        repository: IngestionWorkRepository,
        chunker: ChunkingStrategy,
        embedder: EmbeddingEncoder,
        vector_writer: VectorIndexWriter,
    ) -> None:
        self._repository = repository
        self._chunker = chunker
        self._embedder = embedder
        self._vector_writer = vector_writer

    def process(self, job: IngestionJob) -> int:
        """处理一个任务；返回生成的 Chunk 数，旧版本任务直接标记 superseded。"""

        asset = self._repository.get_asset(job.asset_id)
        if asset is None:
            self._repository.mark_superseded(job.job_id)
            return 0
        if job.event_type == "knowledge_asset.deleted":
            self._vector_writer.delete_asset(asset)
            self._repository.finalize_delete(asset.asset_id)
            return 0
        if asset.status.value == "deleting":
            self._repository.mark_superseded(job.job_id)
            return 0
        if asset.version != job.asset_version:
            self._repository.mark_superseded(job.job_id)
            return 0
        candidates = self._chunker.split(asset)
        chunks = tuple(
            KnowledgeChunk(
                chunk_id=stable_chunk_id(
                    asset_id=asset.asset_id,
                    version=asset.version,
                    logical_key=candidate.logical_key,
                    content_hash=content_digest(candidate.content),
                ),
                asset_id=asset.asset_id,
                asset_version=asset.version,
                space=asset.space,
                chunk_index=index,
                logical_key=candidate.logical_key,
                content=candidate.content,
                content_hash=content_digest(candidate.content),
                metadata={**dict(asset.metadata), **dict(candidate.metadata)},
            )
            for index, candidate in enumerate(candidates)
        )
        vectors = self._embedder.encode([chunk.content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("Embedding encoder returned a mismatched vector count")

        # SQLite 先保存规范 Chunk 与 FTS；Qdrant 写入幂等，失败后可安全重试。
        self._repository.replace_chunks(asset, chunks)
        self._vector_writer.replace_asset_chunks(
            asset=asset,
            chunks=chunks,
            vectors=vectors,
        )
        self._repository.mark_completed(job.job_id, asset.asset_id)
        return len(chunks)

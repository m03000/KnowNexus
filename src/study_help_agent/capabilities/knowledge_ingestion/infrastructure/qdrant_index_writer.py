"""将三个知识空间的 Chunk 幂等写入对应 Qdrant Collection。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from study_help_agent.capabilities.knowledge_ingestion.domain.enums import KnowledgeSpace
from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAsset, KnowledgeChunk
from study_help_agent.infrastructure.search import LocalQdrantClientProvider


class QdrantKnowledgeIndexWriter:
    """按 asset_id 删除旧点后写入新版本，防止缩短后的尾部 Chunk 残留。"""

    def __init__(self, *, client_provider: LocalQdrantClientProvider, collections: Mapping[KnowledgeSpace, str]) -> None:
        self._client_provider = client_provider
        self._collections = dict(collections)

    def replace_asset_chunks(
        self,
        *,
        asset: KnowledgeAsset,
        chunks: Sequence[KnowledgeChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        """确保 Collection 存在，删除资产旧版本并批量 upsert 新向量。"""

        if not chunks:
            raise ValueError("Cannot index an asset without chunks")
        if len(chunks) != len(vectors):
            raise ValueError("Chunk and vector counts must match")
        vector_size = len(vectors[0])
        if vector_size < 1 or any(len(vector) != vector_size for vector in vectors):
            raise ValueError("All embedding vectors must have the same non-zero dimension")

        from qdrant_client.models import (
            Distance,
            FieldCondition,
            Filter,
            MatchValue,
            PointStruct,
            VectorParams,
        )

        client = self._client_provider.get()
        collection = self._collections[asset.space]
        if not client.collection_exists(collection):
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        else:
            configured_size = client.get_collection(collection).config.params.vectors.size
            if configured_size != vector_size:
                raise ValueError(
                    f"Collection {collection} expects vectors of size {configured_size}, got {vector_size}"
                )
        client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="asset_id", match=MatchValue(value=asset.asset_id))]
            ),
            wait=True,
        )
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            metadata = dict(chunk.metadata)
            points.append(PointStruct(
                id=chunk.chunk_id,
                vector=list(vector),
                payload={
                    "text": chunk.content,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "asset_id": asset.asset_id,
                    "asset_version": asset.version,
                    "asset_type": asset.asset_type.value,
                    "space": asset.space.value,
                    "title": asset.title,
                    "source_file": metadata.get("file_path", ""),
                    "section_title": metadata.get("section_title", asset.title),
                    **metadata,
                },
            ))
        client.upsert(collection_name=collection, points=points, wait=True)

    def delete_asset(self, asset: KnowledgeAsset) -> None:
        """按 asset_id 删除指定知识空间中的全部向量点；Collection 尚不存在时视为成功。"""

        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = self._client_provider.get()
        collection = self._collections[asset.space]
        if not client.collection_exists(collection):
            return
        client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="asset_id", match=MatchValue(value=asset.asset_id))]
            ),
            wait=True,
        )

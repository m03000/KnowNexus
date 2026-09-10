"""Qdrant 文档目录与向量召回适配器"""

from collections.abc import Mapping
from pathlib import Path

from study_help_agent.capabilities.rag.application.ports import Embedder
from study_help_agent.capabilities.rag.domain.models import RetrievedChunk
from study_help_agent.infrastructure.search import LocalQdrantClientProvider


class QdrantChunkStore:
    """从本地 Qdrant collection 读取全部文档或执行向量召回。"""

    def __init__(
        self,
        *,
        database_path: Path,
        collection_name: str,
        embedder: Embedder,
        client_provider: LocalQdrantClientProvider | None = None,
        collections: Mapping[str, str] | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._collection_name = collection_name
        self._embedder = embedder
        self._client_provider = client_provider or LocalQdrantClientProvider(
            self._database_path
        )
        self._collections = dict(collections or {})

    def _get_client(self):
        return self._client_provider.get()

    @staticmethod
    def _to_chunk(record, channel: str, score: float | None = None) -> RetrievedChunk:
        payload = record.payload or {}
        return RetrievedChunk(
            chunk_id=str(record.id),
            text=str(payload.get("text", "")),
            source_file=str(payload.get("source_file", "")),
            section_title=str(payload.get("section_title", "")),
            chunk_index=int(payload.get("chunk_index", 0)),
            space=str(payload.get("space", "")),
            asset_id=str(payload.get("asset_id", "")),
            asset_type=str(payload.get("asset_type", "")),
            title=str(payload.get("title", "")),
            metadata=dict(payload),
            retrieval_channels=(channel,),
            vector_score=score,
        )

    def retrieve(self, query: str, limit: int) -> list[RetrievedChunk]:
        """使用 BGE-M3 查询向量执行 Qdrant 语义召回。"""

        vector = self._embedder.encode([query])[0]
        response = self._get_client().query_points(
            collection_name=self._collection_name,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        return [
            self._to_chunk(point, "vector", float(point.score))
            for point in response.points
            if (point.payload or {}).get("text")
        ]

    def retrieve_scoped(
        self, query: str, limit: int, spaces: tuple[str, ...]
    ) -> list[RetrievedChunk]:
        """一次编码查询，并在路由选中的多个 Collection 中执行语义召回。"""

        vector = self._embedder.encode([query])[0]
        client = self._get_client()
        results: list[RetrievedChunk] = []
        for space in spaces:
            collection = self._collections.get(space)
            if not collection or not client.collection_exists(collection):
                continue
            response = client.query_points(
                collection_name=collection,
                query=vector,
                limit=limit,
                with_payload=True,
            )
            results.extend(
                self._to_chunk(point, "vector", float(point.score))
                for point in response.points
                if (point.payload or {}).get("text")
            )
        return sorted(
            results,
            key=lambda chunk: chunk.vector_score or float("-inf"),
            reverse=True,
        )[:limit]

    def encode_query(self, query: str) -> list[float]:
        """只编码一次查询，供逐层树检索复用同一个向量。"""

        return self._embedder.encode([query])[0]

    def retrieve_tree_nodes(
        self,
        *,
        query_vector: list[float],
        parent_ids: tuple[str, ...] = (),
        roots: bool = False,
        project_fingerprints: tuple[str, ...] = (),
        limit: int = 5,
    ) -> list[RetrievedChunk]:
        """在代码 Collection 的指定树层中执行向量选择。"""

        collection = self._collections.get("project_code")
        client = self._get_client()
        if not collection or not client.collection_exists(collection):
            return []
        from qdrant_client import models

        conditions = []
        if roots:
            conditions.append(models.FieldCondition(
                key="tree_node_type",
                match=models.MatchValue(value="project"),
            ))
            if project_fingerprints:
                conditions.append(models.FieldCondition(
                    key="project_fingerprint",
                    match=models.MatchAny(any=list(project_fingerprints)),
                ))
        elif parent_ids:
            conditions.append(models.FieldCondition(
                key="tree_parent_id",
                match=models.MatchAny(any=list(parent_ids)),
            ))
        else:
            return []
        response = client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=models.Filter(must=conditions),
            limit=limit,
            with_payload=True,
        )
        results: list[RetrievedChunk] = []
        seen_nodes: set[str] = set()
        for point in response.points:
            payload = point.payload or {}
            node_id = str(payload.get("tree_node_id") or point.id)
            if not payload.get("text") or node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            results.append(self._to_chunk(point, "tree", float(point.score)))
        return results

    def get_by_metadata(
            self,
            *,
            collection_key: str,
            metadata_filter: Mapping[str, object],
            limit: int = 5,
    ) -> list[RetrievedChunk]:
        """按 payload 字段精确匹配反查文档。

        用于图检索命中节点后取回同一份向量文档,例如:
        """
        collection = self._collections.get(collection_key)
        if not collection or not self._get_client().collection_exists(collection):
            return []
        from qdrant_client import models
        conditions = [
            models.FieldCondition(key=str(k), match=models.MatchValue(value=v))
            for k, v in metadata_filter.items()
        ]
        response = self._get_client().query_points(
            collection_name=collection,
            query_filter=models.Filter(must=conditions),
            limit=limit,
            with_payload=True,
        )
        return [
            self._to_chunk(point, "graph")
            for point in response.points
            if (point.payload or {}).get("text")
        ]

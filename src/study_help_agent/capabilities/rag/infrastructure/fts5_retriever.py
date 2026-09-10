"""把自动入库的 SQLite FTS5 索引适配为 RAG 空间感知关键词召回器。"""

import json
from collections.abc import Sequence
from typing import Protocol

from study_help_agent.capabilities.knowledge_ingestion.domain.enums import KnowledgeSpace
from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class LexicalKnowledgeRepository(Protocol):
    """RAG 读取增量关键词索引所需的最小仓储接口。"""

    def search_lexical(
        self, query: str, *, spaces: Sequence[KnowledgeSpace], limit: int = 20
    ) -> tuple[dict, ...]: ...


class SqliteFTS5Retriever:
    """按路由空间查询 FTS5，并转换成统一 RetrievedChunk。"""

    def __init__(self, repository: LexicalKnowledgeRepository) -> None:
        self._repository = repository

    def retrieve(self, query: str, limit: int) -> list[RetrievedChunk]:
        """兼容旧接口时默认查询个人知识空间。"""

        return self.retrieve_scoped(query, limit, ("personal_knowledge",))

    def retrieve_scoped(
        self, query: str, limit: int, spaces: tuple[str, ...]
    ) -> list[RetrievedChunk]:
        """把受控空间字符串转换成枚举并执行增量关键词召回。"""

        allowed = tuple(KnowledgeSpace(space) for space in spaces)
        rows = self._repository.search_lexical(query, spaces=allowed, limit=limit)
        chunks: list[RetrievedChunk] = []
        for row in rows:
            metadata = json.loads(row.get("metadata_json") or "{}")
            chunks.append(RetrievedChunk(
                chunk_id=str(row["chunk_id"]),
                text=str(row["content"]),
                source_file=str(metadata.get("file_path", "")),
                section_title=str(metadata.get("section_title", "")),
                chunk_index=int(row["chunk_index"]),
                space=str(row["space"]),
                asset_id=str(row["asset_id"]),
                asset_type=str(row.get("asset_type", "")),
                title=str(row.get("asset_title", metadata.get("section_title", ""))),
                retrieval_channels=("lexical",),
                bm25_score=-float(row.get("lexical_score") or 0.0),
            ))
        return chunks

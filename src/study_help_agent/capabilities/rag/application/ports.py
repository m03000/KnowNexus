"""隔离检索图与 Qdrant、Embedding、FTS5、CrossEncoder 实现。"""

from typing import Protocol, Sequence

from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class Embedder(Protocol):
    """把文本编码为向量。"""

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class Retriever(Protocol):
    """统一关键词与向量召回器接口。"""

    def retrieve(self, query: str, limit: int) -> list[RetrievedChunk]: ...


class ScopedRetriever(Protocol):
    """支持在一个或多个逻辑知识空间中召回。"""

    def retrieve_scoped(
        self, query: str, limit: int, spaces: tuple[str, ...]
    ) -> list[RetrievedChunk]: ...


class Reranker(Protocol):
    """对融合候选执行语义精排。"""

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], limit: int
    ) -> list[RetrievedChunk]: ...

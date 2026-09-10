"""把 Retrieval Graph 包装成强类型、带 TTL 缓存的高层检索接口。"""

from collections.abc import Callable

from study_help_agent.capabilities.rag.domain.models import (
    RetrievalQuery,
    RetrievalResult,
)
from study_help_agent.capabilities.rag.infrastructure.retrieval_cache import (
    InMemoryRetrievalCache,
)

from .graph import build_retrieval_graph
from .nodes import RetrievalGraphNodes


class RetrievalMiniAgent:
    """运行完整基础检索链，调用者不需要手工拼接底层步骤。"""

    def __init__(
        self,
        *,
        nodes: RetrievalGraphNodes,
        cache: InMemoryRetrievalCache | None = None,
        index_revision_provider: Callable[[], str] | None = None,
    ) -> None:
        self._graph = build_retrieval_graph(nodes)
        self._cache = cache
        self._index_revision_provider = index_revision_provider

    def retrieve(
        self,
        *,
        query: str,
        history_context: str = "",
        top_k: int = 3,
        recall_k: int = 10,
    ) -> RetrievalResult:
        """返回审查后的文档证据、查询信息、告警和完成状态。"""

        revision = self._index_revision_provider() if self._index_revision_provider else ""
        cache_key = InMemoryRetrievalCache.make_key(
            query, top_k, recall_k, history_context, revision
        )
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
        state = self._graph.invoke(
            {
                "original_query": query,
                "history_context": history_context,
                "top_k": top_k,
                "recall_k": recall_k,
            }
        )
        effective = state.get("effective_query", query)
        result = RetrievalResult(
            query=RetrievalQuery(
                original_text=query.strip(),
                effective_text=effective,
                history_context=history_context.strip(),
                rewritten=effective != query.strip(),
                target_spaces=tuple(state.get("target_spaces", ())),
                routing_reason=state.get("routing_reason", ""),
            ),
            chunks=tuple(state.get("reviewed_results", [])),
            warnings=tuple(state.get("warnings", [])),
            review_summary=state.get("review_summary", ""),
            status=state.get("status", "failed"),
            retry_count=int(state.get("rewrite_count", 0)),
        )
        if self._cache and result.status != "failed":
            self._cache.set(cache_key, result)
        return result

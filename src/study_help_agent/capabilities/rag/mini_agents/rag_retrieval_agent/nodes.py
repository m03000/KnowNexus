"""检索图节点：稳定算法由依赖类执行，LLM 只负责改写与证据审查。"""
from study_help_agent.capabilities.rag.application.ports import Reranker, Retriever
from study_help_agent.capabilities.knowledge_graph.retrieval import GraphRetriever
from study_help_agent.capabilities.rag.llm import RetrievalLLMOperations
from study_help_agent.capabilities.rag.domain import (
    QueryRewritePolicy,
    ReciprocalRankFusion,
)
from .state import RetrievalState


class RetrievalGraphNodes:
    """封装每个可观测阶段，并把局部失败转换为可降级状态。"""

    def __init__(
        self,
        *,
        lexical_retriever: Retriever,
        vector_retriever: Retriever,
        reranker: Reranker,
        llm_operations: RetrievalLLMOperations,
        rewrite_policy: QueryRewritePolicy | None = None,
        fusion: ReciprocalRankFusion | None = None,
        graph_retriever: GraphRetriever | None = None,

    ) -> None:
        self._lexical = lexical_retriever
        self._vector = vector_retriever
        self._reranker = reranker
        self._llm = llm_operations
        self._rewrite_policy = rewrite_policy or QueryRewritePolicy()
        self._fusion = fusion or ReciprocalRankFusion(60)
        self._graph_retriever = graph_retriever

    def prepare_query(self, state: RetrievalState) -> dict:
        """校验参数并判断首次查询是否改写。"""

        query = state["original_query"].strip()
        if not query:
            raise ValueError("检索问题不能为空")
        top_k = int(state.get("top_k", 3))
        recall_k = int(state.get("recall_k", 10))
        if not 1 <= top_k <= 20:
            raise ValueError("top_k 必须在 1 到 20 之间")
        if not top_k <= recall_k <= 100:
            raise ValueError("recall_k 必须不小于 top_k 且不超过 100")
        history = state.get("history_context", "").strip()
        return {
            "original_query": query,
            "effective_query": query,
            "history_context": history,
            "top_k": top_k,
            "recall_k": recall_k,
            "rewrite_required": self._rewrite_policy.needs_rewrite(query, history),
            "rewrite_count": 0,
            "warnings": [],
        }

    @staticmethod
    def route_initial_query(state: RetrievalState) -> str:
        return "rewrite" if state["rewrite_required"] else "retrieve"

    def rewrite_query(self, state: RetrievalState) -> dict:
        """调用 LLM 生成独立检索问句；失败时保留原查询继续执行。"""

        try:
            rewritten = self._llm.rewrite(
                state["original_query"], state.get("history_context", "")
            )
            return {
                "effective_query": rewritten,
                "rewrite_count": int(state.get("rewrite_count", 0)) + 1,
            }
        except Exception as error:
            return {
                "effective_query": state["original_query"],
                "rewrite_count": int(state.get("rewrite_count", 0)) + 1,
                "warnings": [
                    *state.get("warnings", []),
                    f"Query rewrite failed: {error}",
                ],
            }

    def route_spaces(self, state: RetrievalState) -> dict:
        """让 LLM 选择知识空间；模型失败时使用保守关键词规则降级。"""

        query = state["effective_query"]
        route_operation = getattr(self._llm, "route", None)
        if not callable(route_operation):
            return {
                "target_spaces": self._fallback_spaces(query),
                "routing_reason": "检索操作未配置语义路由，使用确定性关键词路由。",
            }
        try:
            route = route_operation(query)
            return {
                "target_spaces": list(route.target_spaces),
                "routing_reason": route.reason,
            }
        except Exception as error:
            spaces = self._fallback_spaces(query)
            return {
                "target_spaces": spaces,
                "routing_reason": "LLM 路由失败，使用确定性关键词降级。",
                "warnings": [
                    *state.get("warnings", []),
                    f"检索空间路由失败：{error}",
                ],
            }

    @staticmethod
    def _fallback_spaces(query: str) -> list[str]:
        """无模型时根据强指示词选择最小知识空间集合。"""

        lowered = query.casefold()
        spaces: list[str] = []
        if any(word in lowered for word in (
            "代码", "源码", "函数", "类", "模块", "项目结构", "file", "function", "class"
        )):
            spaces.append("project_code")
        if any(word in lowered for word in (
            "笔记", "文档", "视频", "知识", "教程", "文章", "note", "document"
        )):
            spaces.append("personal_knowledge")
        if any(word in lowered for word in (
            "我的偏好", "之前决定", "历史任务", "记忆", "preference", "remember"
        )):
            spaces.append("user_memory")
        return spaces or ["personal_knowledge"]

    @staticmethod
    def dispatch_retrieval(state: RetrievalState) -> dict:
        """建立并行召回屏障，本节点不执行业务逻辑。"""

        return {}

    def retrieve_lexical(self, state: RetrievalState) -> dict:
        """执行 FTS5 关键词召回，异常仅标记此通道失败。"""

        try:
            return {
                "lexical_results": self._retrieve(
                    self._lexical,
                    query=state["effective_query"],
                    limit=state["recall_k"],
                    spaces=tuple(state["target_spaces"]),
                ),
                "lexical_error": "",
            }
        except Exception as error:
            return {"lexical_results": [], "lexical_error": str(error)}

    def retrieve_vector(self, state: RetrievalState) -> dict:
        """执行 Qdrant 向量召回，异常仅标记此通道失败。"""

        try:
            return {
                "vector_results": self._retrieve(
                    self._vector,
                    query=state["effective_query"],
                    limit=state["recall_k"],
                    spaces=tuple(state["target_spaces"]),
                ),
                "vector_error": "",
            }
        except Exception as error:
            return {"vector_results": [], "vector_error": str(error)}

    @staticmethod
    def _retrieve(retriever, *, query: str, limit: int, spaces: tuple[str, ...]):
        """优先调用空间感知接口，同时兼容简单测试和旧适配器。"""

        scoped = getattr(retriever, "retrieve_scoped", None)
        if callable(scoped):
            return scoped(query, limit, spaces)
        return retriever.retrieve(query, limit)

    def fuse_results(self, state: RetrievalState) -> dict:
        """以 RRF(k=60) 融合两路排名并汇总降级告警。"""

        warnings = list(state.get("warnings", []))
        if state.get("lexical_error"):
            warnings.append(f"关键词召回失败：{state['lexical_error']}")
        if state.get("vector_error"):
            warnings.append(f"向量召回失败：{state['vector_error']}")
        if state.get("graph_error"):
            warnings.append(f"图结构召回失败：{state['graph_error']}")
        channels = [state.get("lexical_results", []), state.get("vector_results", [])]
        graph_results = state.get("graph_results", [])
        if graph_results:
            channels.append(graph_results)
        # Wiki/graph evidence expands concepts and points back to sources, so it
        # assists the two primary chunk channels without dominating them.
        weights = [1.0, 1.0] + ([0.7] if graph_results else [])
        fused = self._fusion.fuse(channels, state["recall_k"], weights=weights)
        return {"fused_results": fused, "warnings": warnings}

    def rerank_results(self, state: RetrievalState) -> dict:
        """CrossEncoder 精排；失败时按 RRF 顺序降级。"""

        candidates = state.get("fused_results", [])
        try:
            ranked = self._reranker.rerank(
                state["effective_query"], candidates, state["top_k"]
            )
            return {"reranked_results": ranked}
        except Exception as error:
            return {
                "reranked_results": candidates[: state["top_k"]],
                "warnings": [*state.get("warnings", []), f"重排序失败：{error}"],
            }

    def review_results(self, state: RetrievalState) -> dict:
        """让 LLM 审查 Top-K 文档，并过滤仅主题相似但不支撑问题的结果。"""

        candidates = state.get("reranked_results", [])
        if not candidates:
            return {
                "reviewed_results": [],
                "sufficient": False,
                "review_summary": "没有召回可供审查的文档。",
                "review_issues": ["没有检索结果"],
            }
        try:
            review = self._llm.review(state["original_query"], candidates)
            allowed = set(review.relevant_chunk_ids)
            reviewed = [chunk for chunk in candidates if chunk.chunk_id in allowed]
            return {
                "reviewed_results": reviewed,
                "sufficient": bool(review.sufficient and reviewed),
                "review_summary": review.summary,
                "review_issues": review.issues,
            }
        except Exception as error:
            return {
                "reviewed_results": candidates,
                "sufficient": True,
                "review_summary": "审查模型失败，保留重排结果作为降级证据。",
                "review_issues": [str(error)],
                "warnings": [*state.get("warnings", []), f"检索审查失败：{error}"],
            }

    @staticmethod
    def route_after_review(state: RetrievalState) -> str:
        if state.get("sufficient"):
            return "finish"
        if int(state.get("rewrite_count", 0)) < 1:
            return "retry"
        return "finish"

    def prepare_retry(self, state: RetrievalState) -> dict:
        """审查不足时强制执行一次查询改写，随后重新运行完整召回。"""

        return self.rewrite_query(state)

    @staticmethod
    def finalize(state: RetrievalState) -> dict:
        """根据审查后证据和通道失败情况计算最终状态。"""

        chunks = state.get("reviewed_results", [])
        warnings = list(state.get("warnings", []))
        warnings.extend(state.get("review_issues", []))
        if chunks and state.get("sufficient"):
            status = "partial" if warnings else "completed"
        elif chunks:
            status = "partial"
            warnings.append("检索证据相关但不足以完整回答问题")
        else:
            status = "failed"
            warnings.append("没有通过审查的检索证据")
        return {"status": status, "warnings": list(dict.fromkeys(warnings))}

    def retrieve_graph(self, state: RetrievalState) -> dict:
        target_spaces = tuple(state.get("target_spaces", []))
        graph_spaces = {"project_code", "personal_knowledge", "user_memory"}
        if (
            self._graph_retriever is None
            or not graph_spaces.intersection(target_spaces)
        ):
            return {"graph_results": [], "graph_error": ""}
        try:
            return {
                "graph_results": self._graph_retriever.retrieve(
                    query=state["effective_query"],
                    limit=state["recall_k"],
                    spaces=target_spaces,
                ),
                "graph_error": "",
            }
        except Exception as error:
            return {"graph_results": [], "graph_error": str(error)}

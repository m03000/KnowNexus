"""查询、两路召回、融合、重排、审查和重试共享的显式图状态。"""

from typing import Literal, TypedDict

from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class RetrievalState(TypedDict, total=False):
    """记录基础检索链的输入、阶段结果、告警与验收状态。"""

    original_query: str
    history_context: str
    effective_query: str
    top_k: int
    recall_k: int
    rewrite_required: bool
    rewrite_count: int
    target_spaces: list[str]
    routing_reason: str
    lexical_results: list[RetrievedChunk]
    vector_results: list[RetrievedChunk]
    lexical_error: str
    vector_error: str
    fused_results: list[RetrievedChunk]
    reranked_results: list[RetrievedChunk]
    reviewed_results: list[RetrievedChunk]
    graph_results: list[RetrievedChunk]
    graph_error: str
    review_summary: str
    review_issues: list[str]
    sufficient: bool
    warnings: list[str]
    status: Literal["completed", "partial", "failed"]

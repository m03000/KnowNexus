"""GroundedAnswerGraph 的强类型执行入口。"""

from typing import Any

from study_help_agent.capabilities.rag.domain import GroundedAnswer

from .graph import build_grounded_answer_graph
from .nodes import GroundedAnswerGraphNodes


class GroundedAnswerMiniAgent:
    """对已审查检索证据生成、校验和有限修订回答。"""

    def __init__(self, *, nodes: GroundedAnswerGraphNodes) -> None:
        self._graph = build_grounded_answer_graph(nodes)

    def generate(self, *, question: str, chunks: list[dict[str, Any]]) -> GroundedAnswer:
        """运行回答图并恢复稳定领域结果。"""

        state = self._graph.invoke({"question": question, "input_chunks": chunks})
        return GroundedAnswer(
            answer=state["answer"],
            citation_chunk_ids=tuple(state.get("valid_citation_ids", [])),
            insufficient_evidence=state.get("insufficient_evidence", False),
            warnings=tuple(state.get("warnings", [])),
            review_summary=state.get("review_summary", ""),
            status=state.get("status", "partial"),
            revision_count=int(state.get("revision_count", 0)),
        )

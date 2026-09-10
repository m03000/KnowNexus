"""GroundedAnswerGraph 的显式状态协议。"""

from typing import Any, Literal, TypedDict


class GroundedAnswerState(TypedDict, total=False):
    """保存证据、回答草稿、引用校验、审查反馈和最终状态。"""

    question: str
    input_chunks: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    answer: str
    requested_citation_ids: list[str]
    valid_citation_ids: list[str]
    invalid_citation_ids: list[str]
    insufficient_evidence: bool
    citation_validation_passed: bool
    review_passed: bool
    review_summary: str
    review_issues: list[str]
    revision_feedback: list[str]
    revision_count: int
    warnings: list[str]
    status: Literal["completed", "partial", "failed"]

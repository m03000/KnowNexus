"""LearningNoteBuilderGraph 的内容审查、规划和多笔记生成状态协议。"""

from typing import Any, Literal, TypedDict


class LearningNoteBuilderState(TypedDict, total=False):
    """保存来源块、信息清单、动态规划、候选笔记和质量闭环状态。"""

    input_text: str
    cleaned_text: str
    source_type: str
    source_name: str
    source_uri: str
    source_metadata: dict[str, Any]
    scale: Literal["small", "medium", "large"]
    chunks: list[dict[str, Any]]
    chunk_audits: list[dict[str, Any]]
    inventory: list[dict[str, Any]]
    plan: dict[str, Any]
    generated_notes: list[dict[str, Any]]
    quality_passed: bool
    quality_issues: list[str]
    revision_count: int
    metadata: dict[str, Any]
    status: Literal["completed", "partial"]
    warnings: list[str]

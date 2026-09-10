"""统一检索链各阶段交换的数据。"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Literal

class RetrievalSpace(StrEnum):
    """RAG 可查询的三个隔离知识空间。"""

    PROJECT_CODE = "project_code"
    PERSONAL_KNOWLEDGE = "personal_knowledge"
    USER_MEMORY = "user_memory"


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """记录原始查询、实际检索查询和是否经过改写。"""

    original_text: str
    effective_text: str
    history_context: str = ""
    rewritten: bool = False
    target_spaces: tuple[str, ...] = ()
    routing_reason: str = ""


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """携带正文、来源以及各阶段分数的统一文档块。"""

    chunk_id: str
    text: str
    source_file: str = ""
    section_title: str = ""
    chunk_index: int = 0
    space: str = ""
    asset_id: str = ""
    asset_type: str = ""
    title: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    retrieval_channels: tuple[str, ...] = ()
    vector_score: float | None = None
    bm25_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None

    def with_updates(self, **changes) -> "RetrievedChunk":
        """返回不可变文档块的更新副本。"""

        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """基础检索图的最终稳定输出。"""

    query: RetrievalQuery
    chunks: tuple[RetrievedChunk, ...]
    warnings: tuple[str, ...] = ()
    review_summary: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """回答图最终产物，包含有效引用、审查状态和修订次数。"""

    answer: str
    citation_chunk_ids: tuple[str, ...]
    insufficient_evidence: bool
    warnings: tuple[str, ...] = ()
    review_summary: str = ""
    status: Literal["completed", "partial", "failed"] = "completed"
    revision_count: int = 0

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NoteSegment:
    category: str
    title: str
    content: str
    kg_nodes: list[str] = field(default_factory=list)
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedNote:
    title: str
    content: str
    topics: list[str] = field(default_factory=list)
    segments: list[NoteSegment] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SavedNote:
    filename: str
    path: str
    segments_count: int


@dataclass(frozen=True, slots=True)
class BuiltLearningNote:
    """规划图生成的一篇专业学习笔记。"""

    title: str
    introduction: str
    content: str
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_structure_reasonable: bool = False
    processing_notes: list[str] = field(default_factory=list)
    quality_status: str = "completed"
    quality_issues: list[str] = field(default_factory=list)
    revision_count: int = 0
    source_chunk_ids: list[str] = field(default_factory=list)
    covered_item_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NoteBundle:
    """一次材料处理产生的一篇或多篇笔记及全局规划信息。"""

    title: str
    introduction: str
    strategy: str
    notes: list[BuiltLearningNote] = field(default_factory=list)
    audit_summary: str = ""
    planning_rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    warnings: list[str] = field(default_factory=list)

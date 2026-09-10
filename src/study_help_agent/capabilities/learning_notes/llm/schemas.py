from typing import Literal

from pydantic import BaseModel, Field


class NoteSegmentOutput(BaseModel):
    category: str
    title: str
    content: str
    kg_nodes: list[str] = Field(default_factory=list)
    sort_order: int = 0


class NoteSegmentsOutput(BaseModel):
    segments: list[NoteSegmentOutput] = Field(default_factory=list)


class ContentInformationOutput(BaseModel):
    """来源块中必须被规划追踪的有效信息单元。"""

    item_id: str
    category: Literal[
        "concept", "fact", "explanation", "example", "code",
        "procedure", "data", "constraint", "warning", "viewpoint",
    ]
    content: str
    importance: Literal["required", "supporting"] = "required"
    source_excerpt: str = ""


class ChunkAuditOutput(BaseModel):
    """单个来源块的语义内容与局部结构审查。"""

    summary: str
    topics: list[str] = Field(default_factory=list)
    local_structure_quality: Literal["coherent", "partially_coherent", "fragmented"]
    structural_issues: list[str] = Field(default_factory=list)
    information_items: list[ContentInformationOutput] = Field(default_factory=list)


class NoteSectionPlanOutput(BaseModel):
    """一篇笔记中根据材料动态产生的章节规划。"""

    heading: str
    purpose: str
    source_chunk_ids: list[str] = Field(default_factory=list)
    required_item_ids: list[str] = Field(default_factory=list)


class PlannedNoteOutput(BaseModel):
    """一篇候选笔记的目标、主题与动态章节结构。"""

    title: str
    purpose: str
    topics: list[str] = Field(default_factory=list)
    sections: list[NoteSectionPlanOutput] = Field(default_factory=list)


class NotePlanOutput(BaseModel):
    """全局结构审查后生成的一篇或多篇笔记规划。"""

    bundle_title: str
    bundle_introduction: str
    strategy: Literal["single", "sectional", "multiple"]
    rationale: str
    source_structure_reasonable: bool
    audit_summary: str
    notes: list[PlannedNoteOutput] = Field(default_factory=list)


class GeneratedPlannedNoteOutput(BaseModel):
    """按照规划和来源证据生成的一篇完整专业笔记。"""

    title: str
    introduction: str
    topics: list[str] = Field(default_factory=list)
    content: str
    covered_item_ids: list[str] = Field(default_factory=list)
    processing_notes: list[str] = Field(default_factory=list)


class NoteQualityReviewOutput(BaseModel):
    """最终笔记的结构、忠实度和信息覆盖审查。"""

    passed: bool
    structure_professional: bool
    faithful: bool
    coverage_sufficient: bool
    summary: str
    issues: list[str] = Field(default_factory=list)
    missing_item_ids: list[str] = Field(default_factory=list)


class CleanContentOutput(BaseModel):
    """单个内容批次完成深度去噪或多模态融合后的结果。"""

    cleaned_text: str
    processing_notes: list[str] = Field(default_factory=list)

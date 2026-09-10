"""知识点提取的 LLM 结构化输出 Schema。"""
from pydantic import BaseModel, Field


class ExtractedPoint(BaseModel):
    name: str = Field(description="公众认可的专业名词，如 'React 循环'")
    description: str = Field(
        default="",
        description=(
            "知识点自身的、脱离当前文章也成立的一句话概念定义；"
            "禁止概括文章内容或使用‘本文、文中、本笔记、作者提到’等表述"
        ),
    )
    domain: str = Field(default="", description="知识域：agent/ai/...")
    entity_type: str = Field(default="concept",
                             description="concept/technology/framework/language")
    segment_index: int = Field(description="知识点所在的 segment 序号")
    importance: float = Field(
        ge=0.0, le=1.0,
        description="该概念对整篇笔记的重要程度；只有核心概念应高于 0.75",
    )
    granularity_fit: bool = Field(
        default=True,
        description="是否与文章主主题处于相邻粒度，既不过宽也不是实现碎片",
    )
    matched_existing_point_id: str | None = Field(
        default=None,
        description=(
            "若候选与已有知识点是同一概念，填写已有 point_id；"
            "只是相关、上下位或容易混淆时必须为 null"
        ),
    )
    evidence_excerpt: str = Field(
        min_length=2,
        description="知识点所在段落中的简短原文证据，必须能在对应 segment 中找到",
    )


class PointExtractionOutput(BaseModel):
    points: list[ExtractedPoint] = Field(
        default_factory=list,
        max_length=30,
        description="从整篇笔记精选的核心知识点候选，按重要性降序，禁止罗列普通关键词"
    )

"""知识点与笔记关联的领域模型。"""
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class KnowledgePoint:
    point_id: str          # sha256(name) 去重主键
    name: str              # 标准化专业名词
    description: str = ""
    domain: str = ""       # 前端/后端/AI/...
    entity_type: str = "concept"  # concept/technology/framework/language
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class NotePointLink:
    point_id: str
    note_filename: str          # 笔记文件名，外键到文件系统
    segment_index: int          # 第几个 segment
    relevance: str = "defined"  # defined=定义 / mentioned=提及 / core=核心
    evidence_excerpt: str = ""  # 经校验可在对应 segment 中直接找到的原文证据


@dataclass(frozen=True, slots=True)
class PointExtractionResult:
    """一次知识点提取的完整结果，用于 LLM 结构化输出。"""
    knowledge_points: list[KnowledgePoint] = field(default_factory=list)
    links: list[NotePointLink] = field(default_factory=list)

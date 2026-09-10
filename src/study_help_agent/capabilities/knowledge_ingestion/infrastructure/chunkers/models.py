"""切块器内部使用的轻量候选模型和协议。"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAsset


@dataclass(frozen=True, slots=True)
class ChunkCandidate:
    """尚未分配持久化 ID 的语义块。"""

    logical_key: str
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class AssetChunker(Protocol):
    """把一个完整知识资产切成有序语义块。"""

    def split(self, asset: KnowledgeAsset) -> tuple[ChunkCandidate, ...]: ...

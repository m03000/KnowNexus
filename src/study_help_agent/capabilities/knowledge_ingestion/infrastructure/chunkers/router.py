"""根据知识资产类型路由到确定性切块器。"""

from study_help_agent.capabilities.knowledge_ingestion.domain.enums import KnowledgeAssetType, KnowledgeSpace
from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAsset

from .code_chunker import CodeAssetChunker
from .heading_chunker import HeadingAwareChunker
from .memory_chunker import MemoryChunker
from .models import AssetChunker, ChunkCandidate


class AssetChunkerRouter:
    """代码、结构化笔记和用户记忆使用不同切块边界。"""

    def __init__(self, *, heading: AssetChunker | None = None, code: AssetChunker | None = None, memory: AssetChunker | None = None) -> None:
        self._heading = heading or HeadingAwareChunker()
        self._code = code or CodeAssetChunker()
        self._memory = memory or MemoryChunker()

    def split(self, asset: KnowledgeAsset) -> tuple[ChunkCandidate, ...]:
        if asset.asset_type is KnowledgeAssetType.CODE_BLOCK_ANALYSIS:
            chunks = self._code.split(asset)
        elif asset.space is KnowledgeSpace.USER_MEMORY:
            chunks = self._memory.split(asset)
        else:
            chunks = self._heading.split(asset)
        if not chunks:
            raise ValueError(f"Asset produced no chunks: {asset.asset_id}")
        return chunks

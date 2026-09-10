"""为未来用户记忆空间预留的对话事件切块器。"""

from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAsset

from .cleaner import recursive_bound
from .models import ChunkCandidate


class MemoryChunker:
    """当前按受控事件窗口切块；用户记忆自动写入仍默认关闭。"""

    def __init__(self, *, max_characters: int = 1200, overlap: int = 100) -> None:
        self._max_characters = max_characters
        self._overlap = overlap

    def split(self, asset: KnowledgeAsset) -> tuple[ChunkCandidate, ...]:
        parts = recursive_bound(asset.content, max_characters=self._max_characters, overlap=self._overlap)
        return tuple(ChunkCandidate(
            logical_key=f"memory-window:{index}",
            content=part,
            metadata={"section_title": asset.title, "memory_window": index},
        ) for index, part in enumerate(parts))

"""面向代码块解析资产的语义完整切块器。"""

from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAsset

from .cleaner import clean_text, recursive_bound
from .models import ChunkCandidate


class CodeAssetChunker:
    """默认保持代码和解释同块，仅在超长时按受控窗口拆分。"""

    def __init__(self, *, max_characters: int = 4000, overlap: int = 250) -> None:
        self._max_characters = max_characters
        self._overlap = overlap

    def split(self, asset: KnowledgeAsset) -> tuple[ChunkCandidate, ...]:
        parts = recursive_bound(clean_text(asset.content), max_characters=self._max_characters, overlap=self._overlap)
        return tuple(ChunkCandidate(
            logical_key=f"code-part:{index}",
            content=part,
            metadata={"section_title": asset.title, "code_part": index, "code_parts": len(parts)},
        ) for index, part in enumerate(parts))

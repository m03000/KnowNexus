"""面向学习笔记和项目报告的 Markdown 标题感知切块器。"""

import re

from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAsset

from .cleaner import clean_text, recursive_bound
from .models import ChunkCandidate


class HeadingAwareChunker:
    """按标题章节切分，保留 heading_path，并为超长章节递归限长。"""

    _heading = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def __init__(self, *, max_characters: int = 1800, overlap: int = 150) -> None:
        self._max_characters = max_characters
        self._overlap = overlap

    def split(self, asset: KnowledgeAsset) -> tuple[ChunkCandidate, ...]:
        """识别非代码围栏中的标题，按章节生成稳定候选块。"""

        text = clean_text(asset.content)
        sections: list[tuple[tuple[str, ...], str]] = []
        heading_path: list[str] = []
        buffer: list[str] = []
        in_fence = False

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body:
                sections.append((tuple(heading_path), body))
            buffer.clear()

        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            match = None if in_fence else self._heading.match(line)
            if match:
                flush()
                level, title = len(match.group(1)), match.group(2).strip()
                heading_path[:] = heading_path[: level - 1]
                heading_path.append(title)
            buffer.append(line)
        flush()
        candidates: list[ChunkCandidate] = []
        for section_index, (path, body) in enumerate(sections or [((), text)]):
            parts = recursive_bound(body, max_characters=self._max_characters, overlap=self._overlap)
            for part_index, part in enumerate(parts):
                candidates.append(ChunkCandidate(
                    logical_key=f"section:{section_index}:part:{part_index}",
                    content=part,
                    metadata={"heading_path": list(path), "section_title": path[-1] if path else asset.title},
                ))
        return tuple(candidates)

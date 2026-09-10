"""个人知识空间的 LLM Wiki 第三路检索器。"""

from __future__ import annotations

from study_help_agent.capabilities.llm_wiki.infrastructure.repository import (
    SqliteWikiRepository,
)
from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class WikiRetriever:
    """标题/别名、Wiki 全文索引和一跳页面关系的有界检索。"""

    def __init__(self, repository: SqliteWikiRepository) -> None:
        self._repository = repository

    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        if not query.strip() or limit < 1:
            return []
        pages = self._repository.search_pages(query, limit=min(limit, 20))
        return [self._to_chunk(page, index) for index, page in enumerate(pages)]

    @staticmethod
    def _to_chunk(page: dict, index: int) -> RetrievedChunk:
        sources = list(page.get("sources") or [])
        citations = []
        for source in sources:
            locator = str(source.get("locator") or "来源文档")
            citations.append(
                {
                    "source_id": str(source.get("source_id") or ""),
                    "title": str(source.get("title") or ""),
                    "source_ref": str(source.get("source_ref") or ""),
                    "original_path": str(source.get("original_path") or ""),
                    "segment_key": str(source.get("segment_key") or ""),
                    "locator": locator,
                    "evidence_excerpt": str(source.get("evidence_excerpt") or ""),
                }
            )
        source_file = next(
            (item["original_path"] for item in citations if item["original_path"]),
            "",
        )
        return RetrievedChunk(
            chunk_id=f"wiki-page:{page['page_id']}",
            text=str(page.get("body_markdown") or page.get("summary") or ""),
            source_file=source_file,
            section_title=str(page["canonical_title"]),
            chunk_index=index,
            space="personal_knowledge",
            asset_id=str(page["page_id"]),
            asset_type=f"wiki_{page['page_type']}",
            title=str(page["canonical_title"]),
            metadata={
                "wiki_page_id": str(page["page_id"]),
                "wiki_page_type": str(page["page_type"]),
                "wiki_slug": str(page["slug"]),
                "wiki_version": int(page["version"]),
                "citations": citations,
            },
            retrieval_channels=("wiki",),
            bm25_score=-float(page.get("search_score") or 0.0),
        )

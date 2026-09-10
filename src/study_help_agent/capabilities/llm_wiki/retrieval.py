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
        evidence: list[RetrievedChunk] = []
        seen: set[str] = set()
        for page in pages:
            for chunk in self._to_evidence(page):
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    evidence.append(chunk)
                if len(evidence) >= limit:
                    return evidence
        return evidence

    @staticmethod
    def _to_evidence(page: dict) -> list[RetrievedChunk]:
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
        common = {
            "wiki_page_id": str(page["page_id"]), "wiki_page_type": str(page["page_type"]),
            "wiki_slug": str(page["slug"]), "wiki_version": int(page["version"]),
        }
        chunks = []
        for index, citation in enumerate(citations):
            source_id, segment_key = citation["source_id"], citation["segment_key"]
            excerpt = citation["evidence_excerpt"].strip()
            if not excerpt:
                continue
            evidence_key = f"{source_id}:{segment_key}" if source_id and segment_key else f"{page['page_id']}:{index}"
            chunks.append(RetrievedChunk(
                chunk_id=f"wiki-evidence:{evidence_key}", text=excerpt[:1200],
                source_file=citation["original_path"], section_title=citation["locator"],
                chunk_index=index, space="personal_knowledge", asset_id=source_id,
                asset_type="wiki_evidence", title=citation["title"] or str(page["canonical_title"]),
                metadata={**common, **citation, "evidence_key": evidence_key},
                retrieval_channels=("wiki",), bm25_score=-float(page.get("search_score") or 0.0)))
        if chunks:
            return chunks
        # Citation-free pages are navigation hints only; keep a short summary so a
        # full Wiki article can never crowd out normal chunks during reranking.
        summary = str(page.get("summary") or "").strip()
        if not summary:
            return []
        return [RetrievedChunk(chunk_id=f"wiki-summary:{page['page_id']}", text=summary[:800],
            section_title=str(page["canonical_title"]), space="personal_knowledge",
            asset_id=str(page["page_id"]), asset_type="wiki_navigation",
            title=str(page["canonical_title"]), metadata={**common, "navigation_only": True},
            retrieval_channels=("wiki",), bm25_score=-float(page.get("search_score") or 0.0))]

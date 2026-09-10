"""LLM Wiki 浏览、版本历史和回滚接口。"""

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from study_help_agent.api.dependencies import get_app_settings, get_wiki_repository
from study_help_agent.capabilities.llm_wiki.infrastructure import SqliteWikiRepository
from study_help_agent.core.config import Settings
from study_help_agent.capabilities.llm_wiki.infrastructure.obsidian_mcp import ObsidianWikiConfigStore


router = APIRouter(prefix="/api/library/wiki", tags=["LLM Wiki"])
WikiRepository = Annotated[SqliteWikiRepository, Depends(get_wiki_repository)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


class WikiRollbackRequest(BaseModel):
    version: int = Field(ge=1)


def _single_topic(value: str) -> str:
    topic = re.split(r"\s*(?:[/／、,+＋|｜]|\s+与\s+)\s*", value.strip(), maxsplit=1)[0]
    return topic.strip(" -–—:：") or "通用知识"


@router.get("/stats")
def wiki_statistics(repository: WikiRepository):
    """仪表盘使用的 Wiki 内容统计：主题/概念/源文档数与构建累计 Token。"""

    return repository.statistics()


@router.get("/tree")
def wiki_tree(repository: WikiRepository):
    pages = repository.list_pages(status="active")
    topic_pages = [page for page in pages if str(page["page_type"]) == "topic"]
    concept_folder_by_topic = {
        _single_topic(str(page["canonical_title"])): f"wiki-concepts-topic:{page['page_id']}"
        for page in topic_pages
    }
    folders = [
        {"folder_id": "wiki-root", "parent_id": None, "name": "LLM Wiki", "is_system": True},
        {"folder_id": "wiki-index", "parent_id": "wiki-root", "name": "索引", "is_system": True},
        {"folder_id": "wiki-topics", "parent_id": "wiki-root", "name": "主题", "is_system": True},
        {"folder_id": "wiki-concepts", "parent_id": "wiki-root", "name": "概念", "is_system": True},
        {"folder_id": "wiki-syntheses", "parent_id": "wiki-root", "name": "综合", "is_system": True},
        {"folder_id": "wiki-sources", "parent_id": "wiki-root", "name": "来源", "is_system": True},
    ]
    folders.extend(
        {
            "folder_id": folder_id,
            "parent_id": "wiki-concepts",
            "name": topic_name,
            "is_system": True,
        }
        for topic_name, folder_id in sorted(concept_folder_by_topic.items())
    )
    folder_by_type = {
        "topic": "wiki-topics", "concept": "wiki-concepts",
        "synthesis": "wiki-syntheses", "source": "wiki-sources",
    }
    items = [
        {
            **page,
            "item_id": f"wiki:{page['page_id']}",
            "item_type": "wiki",
            "folder_id": (
                concept_folder_by_topic.get(
                    _single_topic(str(page.get("topic_key") or "通用知识")),
                    "wiki-concepts",
                )
                if str(page["page_type"]) == "concept"
                else folder_by_type[str(page["page_type"])]
            ),
            "title": page["canonical_title"],
            "editable": False,
        }
        for page in pages
    ]
    items.insert(0, {
        "item_id": "wiki:index", "page_id": "index", "item_type": "wiki",
        "folder_id": "wiki-index", "title": "Wiki 首页", "page_type": "index",
        "editable": False,
    })
    return {"folders": folders, "items": items}


@router.get("/pages/{page_id}")
def wiki_page(page_id: str, repository: WikiRepository, settings: AppSettings):
    if page_id == "index":
        pages = repository.list_pages(status="active")
        groups = (("topic", "主题"), ("concept", "概念"), ("synthesis", "综合"), ("source", "来源"))
        lines = ["# LLM Wiki", ""]
        for page_type, label in groups:
            lines.extend([f"## {label}", ""])
            matches = [page for page in pages if page["page_type"] == page_type]
            lines.extend(f"- {page['canonical_title']}" for page in matches)
            if not matches:
                lines.append("- 暂无")
            lines.append("")
        return {"page_id": "index", "canonical_title": "Wiki 首页", "page_type": "index", "body_markdown": "\n".join(lines), "version": 1, "sources": []}
    page = repository.get_page(page_id)
    if page is None or page["status"] != "active":
        raise HTTPException(status_code=404, detail="Wiki 页面不存在")
    config = ObsidianWikiConfigStore(settings.runtime_data_directory / "obsidian_wiki.json").load()
    if config.enabled and config.vault_path:
        folder = {"topic":"10 Topics", "concept":"20 Concepts", "synthesis":"30 Syntheses", "source":"40 Sources"}.get(str(page["page_type"]), "40 Sources")
        target = Path(config.vault_path).expanduser() / config.wiki_folder / folder / f"{page['slug']}.md"
        try:
            content = target.read_text(encoding="utf-8")
            content = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)
            return {**page, "body_markdown": content, "storage_backend": "obsidian", "obsidian_path": str(target)}
        except OSError:
            pass
    return {**page, "storage_backend": "local"}


@router.get("/pages/{page_id}/versions")
def wiki_versions(page_id: str, repository: WikiRepository):
    return repository.page_versions(page_id)


@router.post("/pages/{page_id}/rollback")
def rollback_wiki_page(
    page_id: str,
    request: WikiRollbackRequest,
    repository: WikiRepository,
    settings: AppSettings,
):
    page = repository.rollback_page(page_id, request.version)
    if page is None:
        raise HTTPException(status_code=404, detail="页面或历史版本不存在")
    directory = {
        "topic": "topics", "concept": "concepts",
        "synthesis": "syntheses", "source": "sources",
    }[str(page["page_type"])]
    target = settings.runtime_data_directory / "wiki" / directory / f"{page['slug']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(page["body_markdown"]), encoding="utf-8")
    return page

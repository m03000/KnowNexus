"""把标准化来源编译为可检索、可追溯的 Wiki 来源页和概念页。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from study_help_agent.capabilities.learning_notes.application.point_service import (
    KnowledgePointService,
)
from study_help_agent.capabilities.learning_notes.domain.models import NoteSegment
from study_help_agent.capabilities.llm_wiki.infrastructure.repository import (
    SqliteWikiRepository,
)
from study_help_agent.capabilities.llm_wiki.infrastructure.obsidian_mcp import ObsidianMcpPublisher


class WikiBuildService:
    """消费一个来源版本；知识点由现有流程提取，页面由确定性模板编译。"""

    def __init__(
        self,
        *,
        repository: SqliteWikiRepository,
        point_service: KnowledgePointService,
        wiki_root: Path,
        obsidian_publisher: ObsidianMcpPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._point_service = point_service
        self._wiki_root = wiki_root.expanduser().resolve()
        self._obsidian_publisher = obsidian_publisher
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for directory in (".obsidian", "topics", "concepts", "syntheses", "sources", "attachments"):
            (self._wiki_root / directory).mkdir(parents=True, exist_ok=True)

    def process(self, job: dict) -> int:
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        source_id = str(job["source_id"])
        operation = str(job["operation"])
        source = self._repository.get_source(source_id)
        if source is None:
            return 0
        if int(source["version"]) != int(job["source_version"]):
            return 0
        point_source_key = self._point_source_key(source)
        if operation == "delete" or source["status"] == "deleted":
            self._point_service.delete_links_for_note(point_source_key)
            pages = self._repository.remove_source_projection(source_id)
            pages.extend(self._rebuild_global_pages())
            self._materialize(pages)
            self._write_index()
            return len(pages)

        content = self._read_normalized_content(Path(str(source["normalized_path"])))
        segments = self._split_segments(content)
        existing = self._point_service.points_for_source(point_source_key)
        metadata = json.loads(str(source.get("metadata_json") or "{}"))
        points_already_refreshed = bool(metadata.get("knowledge_points_refreshed"))
        extraction = None
        if not existing or (int(source["version"]) > 1 and not points_already_refreshed):
            extraction = self._point_service.extract_and_link(point_source_key, segments)
            self.last_usage = dict(getattr(self._point_service, "last_usage", self.last_usage))
            self._point_service.retain_extracted_links(point_source_key, extraction.links)
        points = self._point_service.points_for_source(point_source_key)
        evidence_by_link = {
            (link.point_id, link.segment_index): link.evidence_excerpt
            for link in (extraction.links if extraction else [])
        }
        concepts = [
            self._concept_projection(point, segments, evidence_by_link)
            for point in points
            if 0 <= int(point["segment_index"]) < len(segments)
        ]
        source_page = self._source_page(source, segments, concepts)
        pages = self._repository.replace_source_projection(
            source=source,
            source_page=source_page,
            concepts=concepts,
        )
        pages.extend(self._rebuild_global_pages())
        self._materialize(pages)
        self._write_index()
        return len(pages)

    def _rebuild_global_pages(self) -> list[dict]:
        """基于现有概念及其来源，确定性生成主题页和跨来源综合页。"""
        concepts = self._repository.concept_pages_with_sources()
        grouped: dict[str, list[dict]] = {}
        for concept in concepts:
            sources = concept.get("sources") or []
            domain = self._normalize_topic(str(concept.get("topic_key") or "通用知识"))
            # 兼容旧页面：没有主题字段时从概念标题的命名空间推断。
            title = str(concept.get("canonical_title") or "").strip()
            if domain == "通用知识" and "：" in title:
                domain = title.split("：", 1)[0].strip() or domain
            elif domain == "通用知识" and ":" in title:
                domain = title.split(":", 1)[0].strip() or domain
            grouped.setdefault(domain, []).append({**concept, "sources": sources})

        pages: list[dict] = []
        links: list[dict] = []
        for topic, members in sorted(grouped.items()):
            digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:16]
            page_id = f"topic:{digest}"
            source_count = len({s["source_id"] for m in members for s in m["sources"]})
            concept_names = "、".join(str(member["canonical_title"]) for member in members[:6])
            intro = f"{topic}主题汇总了 {len(members)} 个核心概念，主要包括{concept_names}，内容来自 {source_count} 份来源。"
            lines = [f"# {topic}", "", "## 简介", "", intro, "", "## 核心概念", ""]
            lines.extend(
                f"- [{member['canonical_title']}](wiki://page/{member['page_id']})：{member.get('summary') or '暂无摘要'}"
                for member in members
            )
            pages.append({
                "page_id": page_id, "page_type": "topic", "canonical_title": topic,
                "slug": f"topic-{digest}", "summary": intro,
                "body_markdown": "\n".join(lines).strip() + "\n", "status": "active",
            })
            links.extend({
                "source_page_id": page_id, "target_page_id": member["page_id"],
                "relation_type": "groups", "anchor_text": member["canonical_title"],
            } for member in members)

        cross_source = [
            concept for concept in concepts
            if len({source["source_id"] for source in concept.get("sources") or []}) > 1
        ]
        if cross_source:
            page_id = "synthesis:cross-source"
            lines = ["# 跨文档知识综合", "", "以下概念由多份独立来源共同支撑。", "", "## 共同结论", ""]
            for concept in cross_source:
                source_titles = "、".join(sorted({s["title"] for s in concept["sources"]}))
                lines.append(f"- **[{concept['canonical_title']}](wiki://page/{concept['page_id']})**：{concept.get('summary') or '暂无摘要'}（来源：{source_titles}）")
            pages.append({
                "page_id": page_id, "page_type": "synthesis", "canonical_title": "跨文档知识综合",
                "slug": "cross-source-synthesis", "summary": "多来源共同支撑的知识结论",
                "body_markdown": "\n".join(lines).strip() + "\n", "status": "active",
            })
            links.extend({
                "source_page_id": page_id, "target_page_id": concept["page_id"],
                "relation_type": "synthesizes", "anchor_text": concept["canonical_title"],
            } for concept in cross_source)
        return self._repository.replace_global_projection(pages, links)

    @staticmethod
    def _point_source_key(source: dict) -> str:
        """兼容现有图谱键：笔记沿用 filename，文档沿用 document:<id>。"""

        if str(source.get("source_kind")) == "generated_note":
            return str(source.get("source_ref") or source["source_id"])
        return str(source["source_id"])

    @staticmethod
    def _read_normalized_content(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        if text.startswith("---\n"):
            _, separator, remainder = text[4:].partition("\n---\n")
            if separator:
                return remainder.lstrip("\n")
        return text

    @staticmethod
    def _split_segments(content: str) -> list[NoteSegment]:
        segments: list[NoteSegment] = []
        title = "正文"
        lines: list[str] = []
        for line in content.splitlines():
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading and lines:
                segments.append(
                    NoteSegment(
                        category="wiki_source",
                        title=title,
                        content="\n".join(lines).strip(),
                        sort_order=len(segments),
                    )
                )
                lines = []
            if heading:
                title = heading.group(2).strip()
            lines.append(line)
        if lines:
            segments.append(
                NoteSegment(
                    category="wiki_source",
                    title=title,
                    content="\n".join(lines).strip(),
                    sort_order=len(segments),
                )
            )
        return [segment for segment in segments if segment.content]

    @staticmethod
    def _concept_projection(
        point: dict,
        segments: list[NoteSegment],
        evidence_by_link: dict[tuple[str, int], str],
    ) -> dict:
        index = int(point["segment_index"])
        segment = segments[index]
        segment_key = hashlib.sha256(
            f"{segment.title}\n{segment.content}".encode("utf-8")
        ).hexdigest()[:24]
        exact = evidence_by_link.get((str(point["point_id"]), index), "").strip()
        evidence = exact or WikiBuildService._plain_excerpt(segment.content, 420)
        return {
            "point_id": str(point["point_id"]),
            "name": str(point["name"]),
            "description": str(point.get("description") or ""),
            "domain": WikiBuildService._normalize_topic(str(point.get("domain") or "")),
            "entity_type": str(point.get("entity_type") or "concept"),
            "segment_key": segment_key,
            "locator": segment.title or f"段落 {index + 1}",
            "evidence_excerpt": evidence,
        }

    @staticmethod
    def _source_page(source: dict, segments: list[NoteSegment], concepts: list[dict]) -> dict:
        source_id = str(source["source_id"])
        digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:20]
        summary = ""
        for segment in segments:
            summary = WikiBuildService._plain_excerpt(segment.content, 500)
            if summary:
                break
        lines = [f"# {source['title']}", "", summary]
        original_path = str(source.get("original_path") or "")
        if original_path:
            scheme = "note" if str(source.get("source_kind")) == "generated_note" else "document"
            lines.extend(["", f"> 原始文件：[{source['title']}]({scheme}://{source['source_ref']})"])
        lines.extend(["", "## 目录"])
        lines.extend(f"- {segment.title}" for segment in segments if segment.title)
        lines.extend(["", "## 核心概念"])
        if concepts:
            lines.extend(
                f"- [{concept['name']}](wiki://page/concept:{concept['point_id']})"
                for concept in concepts
            )
        else:
            lines.append("- 暂未提取到满足质量阈值的核心概念。")
        return {
            "page_id": f"source:{digest}",
            "page_type": "source",
            "canonical_title": str(source["title"]),
            "slug": f"source-{digest}",
            "summary": summary,
            "body_markdown": "\n".join(lines).strip() + "\n",
            "status": "active",
        }

    @staticmethod
    def _plain_excerpt(content: str, limit: int) -> str:
        text = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)
        text = re.sub(r"[`*_>#\[\]]", "", text)
        return re.sub(r"\s+", " ", text).strip()[:limit]

    @staticmethod
    def _normalize_topic(value: str) -> str:
        """避免模型把多个主题用分隔符拼成一个目录名。"""

        topic = re.split(r"\s*(?:[/／、,+＋|｜]|\s+与\s+)\s*", value.strip(), maxsplit=1)[0]
        return topic.strip(" -–—:：") or "通用知识"

    def _materialize(self, pages: list[dict]) -> None:
        for page in pages:
            page_type = str(page.get("page_type") or "source")
            slug = str(page.get("slug") or "")
            if not slug:
                continue
            directory_name = {
                "concept": "concepts",
                "source": "sources",
                "topic": "topics",
                "synthesis": "syntheses",
            }.get(page_type, "sources")
            target = self._wiki_root / directory_name / f"{slug}.md"
            if page.get("status") in {"deleted", "archived"}:
                target.unlink(missing_ok=True)
                continue
            self._atomic_write(target, str(page.get("body_markdown") or ""))
        if self._obsidian_publisher is not None:
            try:
                self._obsidian_publisher.publish(pages)
            except Exception:
                # 本地 SQLite 与 Markdown 是永久降级路径；MCP 故障不阻断 Wiki 构建。
                pass

    def _write_index(self) -> None:
        pages = self._repository.list_pages(status="active")
        lines = ["# LLM Wiki", ""]
        for page_type, heading in (("topic", "主题"), ("concept", "概念"), ("synthesis", "综合"), ("source", "来源")):
            lines.extend([f"## {heading}", ""])
            matches = [page for page in pages if page["page_type"] == page_type]
            if matches:
                directory = {"topic": "topics", "concept": "concepts", "synthesis": "syntheses", "source": "sources"}[page_type]
                lines.extend(
                    f"- [{page['canonical_title']}](./{directory}/{page['slug']}.md)"
                    for page in matches
                )
            else:
                lines.append("- 暂无")
            lines.append("")
        self._atomic_write(self._wiki_root / "index.md", "\n".join(lines))

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

"""LLM Wiki SQLite 仓储：来源、页面、引用、链接和构建队列。"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence

import jieba

from study_help_agent.capabilities.llm_wiki.domain import WikiSourceDraft
from study_help_agent.infrastructure.persistence.sqlite import SqliteConnectionFactory


class SqliteWikiRepository:
    def __init__(self, connections: SqliteConnectionFactory) -> None:
        self._connections = connections

    def get_source(self, source_id: str) -> dict | None:
        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT * FROM wiki_sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_source(
        self,
        draft: WikiSourceDraft,
        *,
        normalized_path: str,
        content_hash: str,
        version: int,
    ) -> None:
        metadata_json = json.dumps(draft.metadata, ensure_ascii=False, sort_keys=True)
        with self._connections.connect() as connection:
            connection.execute(
                """
                INSERT INTO wiki_sources (
                    source_id, source_kind, source_ref, original_path, title,
                    media_type, normalized_path, content_hash, status, version,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    source_ref = excluded.source_ref,
                    original_path = excluded.original_path,
                    title = excluded.title,
                    media_type = excluded.media_type,
                    normalized_path = excluded.normalized_path,
                    content_hash = excluded.content_hash,
                    status = 'active',
                    version = excluded.version,
                    metadata_json = excluded.metadata_json,
                    updated_at = datetime('now')
                """,
                (
                    draft.source_id,
                    draft.source_kind,
                    draft.source_ref,
                    draft.original_path,
                    draft.title,
                    draft.media_type,
                    normalized_path,
                    content_hash,
                    version,
                    metadata_json,
                ),
            )
            delay_seconds = int(draft.metadata.get("wiki_build_delay_seconds") or 0)
            self._enqueue(
                connection,
                draft.source_id,
                "upsert",
                version,
                delay_seconds=max(0, min(delay_seconds, 300)),
            )

    def mark_source_deleted(self, source_id: str) -> int | None:
        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT version FROM wiki_sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is None:
                return None
            version = int(row["version"]) + 1
            connection.execute(
                """
                UPDATE wiki_sources
                SET status = 'deleted', version = ?, updated_at = datetime('now')
                WHERE source_id = ?
                """,
                (version, source_id),
            )
            self._enqueue(connection, source_id, "delete", version)
            return version

    def pending_jobs(self, limit: int = 100) -> list[dict]:
        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM wiki_build_queue
                WHERE status = 'pending' AND scheduled_at <= datetime('now')
                ORDER BY scheduled_at, queue_id
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_running_jobs(self) -> None:
        with self._connections.connect() as connection:
            connection.execute(
                """
                UPDATE wiki_build_queue
                SET status = 'pending', started_at = NULL
                WHERE status = 'running'
                """
            )

    def claim_jobs(self, limit: int) -> list[dict]:
        with self._connections.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM wiki_build_queue
                WHERE status = 'pending' AND scheduled_at <= datetime('now')
                ORDER BY scheduled_at, queue_id
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
            queue_ids = [int(row["queue_id"]) for row in rows]
            if queue_ids:
                placeholders = ",".join("?" for _ in queue_ids)
                connection.execute(
                    f"""
                    UPDATE wiki_build_queue
                    SET status = 'running', attempts = attempts + 1,
                        started_at = datetime('now'), last_error = ''
                    WHERE queue_id IN ({placeholders})
                    """,
                    queue_ids,
                )
        return [{**dict(row), "attempts": int(row["attempts"]) + 1} for row in rows]

    def mark_job_completed(self, queue_id: int) -> None:
        with self._connections.connect() as connection:
            connection.execute(
                """
                UPDATE wiki_build_queue
                SET status = 'completed', finished_at = datetime('now')
                WHERE queue_id = ?
                """,
                (queue_id,),
            )

    def mark_job_failed(self, queue_id: int, error: str, *, max_attempts: int) -> None:
        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT attempts FROM wiki_build_queue WHERE queue_id = ?", (queue_id,)
            ).fetchone()
            if row is None:
                return
            exhausted = int(row["attempts"]) >= max_attempts
            connection.execute(
                """
                UPDATE wiki_build_queue
                SET status = ?, last_error = ?, started_at = NULL,
                    finished_at = CASE WHEN ? THEN datetime('now') ELSE NULL END
                WHERE queue_id = ?
                """,
                ("failed" if exhausted else "pending", error[:2000], exhausted, queue_id),
            )

    def start_build(self, source_id: str, operation: str) -> str:
        build_id = uuid.uuid4().hex
        with self._connections.connect() as connection:
            connection.execute(
                """
                INSERT INTO wiki_builds (
                    build_id, trigger_kind, status, source_ids_json, started_at
                ) VALUES (?, ?, 'running', ?, datetime('now'))
                """,
                (build_id, operation, json.dumps([source_id], ensure_ascii=False)),
            )
        return build_id

    def finish_build(
        self, build_id: str, *, error: str = "",
        input_tokens: int = 0, output_tokens: int = 0,
    ) -> None:
        with self._connections.connect() as connection:
            connection.execute(
                """
                UPDATE wiki_builds
                SET status = ?, error_message = ?, input_tokens = ?, output_tokens = ?,
                    finished_at = datetime('now')
                WHERE build_id = ?
                """,
                ("failed" if error else "completed", error[:4000],
                 max(0, int(input_tokens)), max(0, int(output_tokens)), build_id),
            )

    def replace_source_projection(
        self,
        *,
        source: dict,
        source_page: dict,
        concepts: Sequence[dict],
    ) -> list[dict]:
        """原子替换一个来源贡献的页面、引用和链接，并刷新受影响概念页。"""

        source_id = str(source["source_id"])
        source_page_id = str(source_page["page_id"])
        with self._connections.connect() as connection:
            old_rows = connection.execute(
                "SELECT page_id FROM wiki_page_sources WHERE source_id = ?", (source_id,)
            ).fetchall()
            affected = {str(row["page_id"]) for row in old_rows}
            connection.execute(
                "DELETE FROM wiki_page_sources WHERE source_id = ?", (source_id,)
            )
            connection.execute(
                "DELETE FROM wiki_links WHERE source_page_id = ?", (source_page_id,)
            )
            self._upsert_page(connection, source_page)
            self._insert_citation(
                connection,
                page_id=source_page_id,
                source_id=source_id,
                segment_key="source",
                locator="来源文档",
                evidence_excerpt=str(source_page.get("summary") or ""),
            )
            affected.add(source_page_id)

            for concept in concepts:
                page = {
                    "page_id": f"concept:{concept['point_id']}",
                    "page_type": "concept",
                    "canonical_title": concept["name"],
                    "slug": f"concept-{str(concept['point_id'])[:20]}",
                    "summary": concept.get("description", ""),
                    "topic_key": concept.get("domain", "") or "通用知识",
                    "body_markdown": "",
                    "status": "active",
                }
                self._upsert_page(connection, page)
                page_id = str(page["page_id"])
                affected.add(page_id)
                self._insert_citation(
                    connection,
                    page_id=page_id,
                    source_id=source_id,
                    segment_key=str(concept["segment_key"]),
                    locator=str(concept.get("locator") or ""),
                    evidence_excerpt=str(concept.get("evidence_excerpt") or ""),
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO wiki_links (
                        source_page_id, target_page_id, relation_type,
                        anchor_text, confidence
                    ) VALUES (?, ?, 'contains', ?, 1.0)
                    """,
                    (source_page_id, page_id, str(concept["name"])),
                )
                alias = str(concept["name"]).strip()
                connection.execute(
                    """
                    INSERT INTO wiki_aliases (alias_normalized, alias, page_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(alias_normalized) DO UPDATE SET
                        alias = excluded.alias, page_id = excluded.page_id
                    """,
                    (self._normalize_alias(alias), alias, page_id),
                )

            self._refresh_concepts(connection, affected)
            rows = self._pages(connection, affected)
        return rows

    def remove_source_projection(self, source_id: str) -> list[dict]:
        with self._connections.connect() as connection:
            rows = connection.execute(
                "SELECT page_id FROM wiki_page_sources WHERE source_id = ?", (source_id,)
            ).fetchall()
            affected = {str(row["page_id"]) for row in rows}
            source_pages = connection.execute(
                """
                SELECT page_id, slug, page_type FROM wiki_pages
                WHERE page_type = 'source'
                  AND page_id IN (
                      SELECT page_id FROM wiki_page_sources WHERE source_id = ?
                  )
                """,
                (source_id,),
            ).fetchall()
            source_page_rows = [dict(row) for row in source_pages]
            source_page_ids = {str(row["page_id"]) for row in source_page_rows}
            connection.execute(
                "DELETE FROM wiki_page_sources WHERE source_id = ?", (source_id,)
            )
            for page_id in source_page_ids:
                current = connection.execute(
                    "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
                ).fetchone()
                if current is not None:
                    self._snapshot_page(connection, current)
                connection.execute("DELETE FROM wiki_pages WHERE page_id = ?", (page_id,))
                self._delete_fts(connection, page_id)
                affected.discard(page_id)
            self._refresh_concepts(connection, affected)
            pages = self._pages(connection, affected)
        deleted = [{**row, "status": "deleted"} for row in source_page_rows]
        return [*pages, *deleted]

    def search_pages(self, query: str, *, limit: int = 10) -> list[dict]:
        """标题/别名精确命中 + FTS，随后补充一跳链接页面。"""

        actual_limit = min(max(limit, 1), 50)
        normalized = self._normalize_alias(query)
        tokens = [item for item in jieba.lcut(query) if item.strip()]
        expression = " OR ".join(f'"{item.replace(chr(34), "")}"' for item in tokens)
        with self._connections.connect() as connection:
            ranked: list[dict] = []
            seen: set[str] = set()
            alias = connection.execute(
                """
                SELECT wp.*, -100.0 AS search_score
                FROM wiki_aliases wa
                JOIN wiki_pages wp ON wp.page_id = wa.page_id
                WHERE wa.alias_normalized = ? AND wp.status = 'active'
                """,
                (normalized,),
            ).fetchone()
            if alias:
                ranked.append(dict(alias))
                seen.add(str(alias["page_id"]))
            if expression:
                rows = connection.execute(
                    """
                    SELECT wp.*, bm25(wiki_pages_fts, 0.0, 8.0, 3.0, 1.0) AS search_score
                    FROM wiki_pages_fts
                    JOIN wiki_pages wp ON wp.page_id = wiki_pages_fts.page_id
                    WHERE wiki_pages_fts MATCH ? AND wp.status = 'active'
                    ORDER BY search_score
                    LIMIT ?
                    """,
                    (expression, actual_limit),
                ).fetchall()
                for row in rows:
                    page_id = str(row["page_id"])
                    if page_id not in seen:
                        ranked.append(dict(row))
                        seen.add(page_id)
            seed_ids = tuple(seen)
            if seed_ids and len(ranked) < actual_limit:
                placeholders = ",".join("?" for _ in seed_ids)
                linked = connection.execute(
                    f"""
                    SELECT DISTINCT wp.*, 10.0 AS search_score
                    FROM wiki_links wl
                    JOIN wiki_pages wp ON wp.page_id = CASE
                        WHEN wl.source_page_id IN ({placeholders}) THEN wl.target_page_id
                        ELSE wl.source_page_id
                    END
                    WHERE (wl.source_page_id IN ({placeholders})
                           OR wl.target_page_id IN ({placeholders}))
                      AND wp.status = 'active'
                    LIMIT ?
                    """,
                    (*seed_ids, *seed_ids, *seed_ids, actual_limit - len(ranked)),
                ).fetchall()
                for row in linked:
                    page_id = str(row["page_id"])
                    if page_id not in seen:
                        ranked.append(dict(row))
                        seen.add(page_id)
            for page in ranked:
                page["sources"] = self._page_sources(connection, str(page["page_id"]))
        return ranked[:actual_limit]

    def list_pages(self, *, status: str | None = None) -> list[dict]:
        with self._connections.connect() as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM wiki_pages WHERE status = ? ORDER BY canonical_title",
                    (status,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM wiki_pages ORDER BY canonical_title"
                ).fetchall()
        return [dict(row) for row in rows]

    def statistics(self) -> dict:
        """返回 Wiki 内容统计：主题/概念页数、进入 Wiki 的源文档数与构建累计 Token。"""

        with self._connections.connect() as connection:
            count_pages = lambda page_type: int(
                connection.execute(
                    "SELECT COUNT(*) FROM wiki_pages WHERE page_type = ? AND status = 'active'",
                    (page_type,),
                ).fetchone()[0]
            )
            topics = count_pages("topic")
            concepts = count_pages("concept")
            documents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM wiki_sources WHERE status = 'active'"
                ).fetchone()[0]
            )
            build_tokens = int(
                connection.execute(
                    "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM wiki_builds"
                ).fetchone()[0]
            )
        return {
            "topics": topics,
            "concepts": concepts,
            "documents": documents,
            "build_tokens": build_tokens,
        }

    def get_page(self, page_id: str) -> dict | None:
        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
            if row is None:
                return None
            page = dict(row)
            page["sources"] = self._page_sources(connection, page_id)
            if str(page.get("page_type")) == "concept":
                page["body_markdown"] = self._concept_body(page, page["sources"])
            elif str(page.get("page_type")) == "topic" and "## 简介" not in str(page.get("body_markdown") or ""):
                body = str(page.get("body_markdown") or "")
                first, separator, rest = body.partition("\n")
                page["body_markdown"] = f"{first}\n\n## 简介\n\n{page.get('summary') or ''}\n\n{rest.lstrip()}" if separator else body
            elif str(page.get("page_type")) == "source" and page["sources"]:
                source = page["sources"][0]
                scheme = "note" if str(source.get("source_kind")) == "generated_note" else "document"
                link = f"> 原始文件：[{source['title']}]({scheme}://{source['source_ref']})"
                body = str(page.get("body_markdown") or "")
                page["body_markdown"] = re.sub(r"> 原始文件：[^\n]+", link, body)
            return page

    def page_versions(self, page_id: str) -> list[dict]:
        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT page_id, version, canonical_title, summary, status, created_at
                FROM wiki_page_versions WHERE page_id = ? ORDER BY version DESC
                """,
                (page_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rollback_page(self, page_id: str, version: int) -> dict | None:
        """恢复历史正文，同时保留当前版本，形成可再次回滚的新版本。"""
        with self._connections.connect() as connection:
            target = connection.execute(
                "SELECT * FROM wiki_page_versions WHERE page_id = ? AND version = ?",
                (page_id, version),
            ).fetchone()
            current = connection.execute(
                "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
            if target is None:
                return None
            if current is not None:
                self._snapshot_page(connection, current)
            restored = {
                **(dict(current) if current is not None else {}),
                "page_id": target["page_id"],
                "page_type": target["page_type"],
                "slug": target["slug"],
                "canonical_title": target["canonical_title"],
                "topic_key": target["topic_key"],
                "summary": target["summary"],
                "body_markdown": target["body_markdown"],
                "status": target["status"],
                "_base_version": max(
                    version, int(current["version"]) if current is not None else version
                ),
            }
            self._upsert_page(connection, restored, snapshot=False)
            row = connection.execute(
                "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
        return dict(row) if row else None

    def replace_global_projection(self, pages: Sequence[dict], links: Sequence[dict]) -> list[dict]:
        """原子重建派生的主题页和综合页，清理已经失去依据的旧页面。"""
        with self._connections.connect() as connection:
            old = connection.execute(
                "SELECT * FROM wiki_pages WHERE page_type IN ('topic', 'synthesis')"
            ).fetchall()
            old_by_id = {str(row["page_id"]): dict(row) for row in old}
            desired_ids = {str(page["page_id"]) for page in pages}
            for page_id, row in old_by_id.items():
                if page_id in desired_ids:
                    continue
                self._snapshot_page(connection, row)
                connection.execute("DELETE FROM wiki_pages WHERE page_id = ?", (page_id,))
                self._delete_fts(connection, page_id)
            connection.execute(
                """DELETE FROM wiki_links
                   WHERE relation_type IN ('groups', 'synthesizes', 'relates')"""
            )
            for page in pages:
                self._upsert_page(connection, page)
            for link in links:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO wiki_links
                    (source_page_id, target_page_id, relation_type, anchor_text, confidence)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        link["source_page_id"], link["target_page_id"],
                        link["relation_type"], link.get("anchor_text", ""),
                        float(link.get("confidence", 1.0)),
                    ),
                )
            materialized = [dict(row) for row in old if str(row["page_id"]) not in desired_ids]
            materialized = [{**row, "status": "deleted"} for row in materialized]
            materialized.extend(self._pages(connection, desired_ids))
        return materialized

    def concept_pages_with_sources(self) -> list[dict]:
        with self._connections.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM wiki_pages WHERE page_type = 'concept' AND status = 'active'"
            ).fetchall()
            pages = [dict(row) for row in rows]
            for page in pages:
                page["sources"] = self._page_sources(connection, str(page["page_id"]))
        return pages

    def graph_data(self) -> dict:
        """导出 Wiki 页面和内部链接，供笔记图谱统一投影。"""
        with self._connections.connect() as connection:
            page_rows = connection.execute(
                "SELECT * FROM wiki_pages WHERE status = 'active'"
            ).fetchall()
            links = connection.execute(
                """
                SELECT wl.* FROM wiki_links wl
                JOIN wiki_pages source ON source.page_id = wl.source_page_id
                JOIN wiki_pages target ON target.page_id = wl.target_page_id
                WHERE source.status = 'active' AND target.status = 'active'
                """
            ).fetchall()
            source_links = connection.execute(
                """
                SELECT DISTINCT wps.page_id, ws.source_kind, ws.source_ref
                FROM wiki_page_sources wps
                JOIN wiki_sources ws ON ws.source_id = wps.source_id
                JOIN wiki_pages wp ON wp.page_id = wps.page_id
                WHERE wp.page_type = 'source' AND wp.status = 'active'
                  AND ws.status = 'active'
                """
            ).fetchall()
        source_ref_by_page = {
            str(row["page_id"]): {
                "source_kind": str(row["source_kind"]),
                "source_ref": str(row["source_ref"]),
                "source_node_id": (
                    f"note:{row['source_ref']}"
                    if str(row["source_kind"]) == "generated_note"
                    else f"note:document:{row['source_ref']}"
                ),
            }
            for row in source_links
        }
        nodes = [{
            "id": f"wiki:{row['page_id']}",
            "label": row["canonical_title"],
            "node_type": f"wiki_{row['page_type']}",
            "domain": "wiki",
            "summary": (
                f"来源文档：{row['canonical_title']}"
                if str(row["page_type"]) == "source"
                else row["summary"]
            ),
            "payload": {
                "page_id": row["page_id"], "page_type": row["page_type"],
                "version": row["version"], "slug": row["slug"],
                **source_ref_by_page.get(str(row["page_id"]), {}),
            },
        } for row in page_rows]
        edges = [{
            "source": f"wiki:{row['source_page_id']}",
            "target": f"wiki:{row['target_page_id']}",
            "edge_type": row["relation_type"],
            "label": row["relation_type"],
            "weight": row["confidence"],
        } for row in links]
        for row in source_links:
            source_node_id = (
                f"note:{row['source_ref']}"
                if str(row["source_kind"]) == "generated_note"
                else f"note:document:{row['source_ref']}"
            )
            edges.append({
                "source": f"wiki:{row['page_id']}", "target": source_node_id,
                "edge_type": "derived_from", "label": "derived_from", "weight": 1.0,
            })
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _enqueue(
        connection,
        source_id: str,
        operation: str,
        version: int,
        *,
        delay_seconds: int = 0,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO wiki_build_queue
                (source_id, operation, source_version, scheduled_at)
            VALUES (?, ?, ?, datetime('now', ?))
            """,
            (source_id, operation, version, f"+{delay_seconds} seconds"),
        )

    def _upsert_page(self, connection, page: dict, *, snapshot: bool = True) -> None:
        body = str(page.get("body_markdown") or "")
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        existing = connection.execute(
            "SELECT content_hash, version FROM wiki_pages WHERE page_id = ?",
            (page["page_id"],),
        ).fetchone()
        version = (
            int(existing["version"])
            if existing
            else int(page.get("_base_version", 0))
        )
        if existing is None or str(existing["content_hash"]) != content_hash:
            version += 1
            if snapshot and existing is not None:
                current = connection.execute(
                    "SELECT * FROM wiki_pages WHERE page_id = ?", (page["page_id"],)
                ).fetchone()
                if current is not None:
                    self._snapshot_page(connection, current)
        connection.execute(
            """
            INSERT INTO wiki_pages (
                page_id, page_type, canonical_title, slug, summary,
                body_markdown, content_hash, status, version, topic_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_id) DO UPDATE SET
                canonical_title = excluded.canonical_title,
                slug = excluded.slug,
                summary = excluded.summary,
                body_markdown = excluded.body_markdown,
                content_hash = excluded.content_hash,
                status = excluded.status,
                version = excluded.version,
                topic_key = excluded.topic_key,
                updated_at = datetime('now')
            """,
            (
                page["page_id"], page["page_type"], page["canonical_title"],
                page["slug"], page.get("summary", ""), body, content_hash,
                page.get("status", "active"), version,
                page.get("topic_key", ""),
            ),
        )
        self._index_page(connection, str(page["page_id"]))

    @staticmethod
    def _snapshot_page(connection, row) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO wiki_page_versions
            (page_id, version, page_type, slug, canonical_title, topic_key,
             summary, body_markdown, content_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["page_id"], row["version"], row["page_type"], row["slug"],
                row["canonical_title"], row["topic_key"], row["summary"],
                row["body_markdown"], row["content_hash"], row["status"],
            ),
        )

    @staticmethod
    def _insert_citation(
        connection,
        *,
        page_id: str,
        source_id: str,
        segment_key: str,
        locator: str,
        evidence_excerpt: str,
    ) -> None:
        contribution_hash = hashlib.sha256(
            f"{source_id}\n{segment_key}\n{evidence_excerpt}".encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            INSERT OR REPLACE INTO wiki_page_sources (
                page_id, source_id, segment_key, locator,
                evidence_excerpt, contribution_hash
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (page_id, source_id, segment_key, locator, evidence_excerpt, contribution_hash),
        )

    def _refresh_concepts(self, connection, page_ids: set[str]) -> None:
        for page_id in sorted(page_ids):
            row = connection.execute(
                "SELECT * FROM wiki_pages WHERE page_id = ? AND page_type = 'concept'",
                (page_id,),
            ).fetchone()
            if row is None:
                continue
            sources = self._page_sources(connection, page_id)
            if not sources:
                self._snapshot_page(connection, row)
                connection.execute(
                    """
                    UPDATE wiki_pages
                    SET status = 'archived', updated_at = datetime('now')
                    WHERE page_id = ?
                    """,
                    (page_id,),
                )
                self._delete_fts(connection, page_id)
                continue
            self._upsert_page(
                connection,
                {**dict(row), "body_markdown": self._concept_body(dict(row), sources),
                 "status": "active"},
            )

    @staticmethod
    def _concept_body(page: dict, sources: list[dict]) -> str:
        lines = [f"# {page['canonical_title']}", "", str(page.get("summary") or "").strip()]
        lines.extend(["", "## 来源"])
        for source in sources:
            locator = str(source.get("locator") or "来源文档")
            excerpt = str(source.get("evidence_excerpt") or "").strip().replace("\n", " ")
            scheme = "note" if str(source.get("source_kind")) == "generated_note" else "document"
            target = str(source.get("source_ref") or "")
            lines.append(f"- **[{source['title']}]({scheme}://{target}) · {locator}**：{excerpt}")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _page_sources(connection, page_id: str) -> list[dict]:
        rows = connection.execute(
            """
            SELECT wps.*, ws.title, ws.source_kind, ws.source_ref, ws.original_path
            FROM wiki_page_sources wps
            JOIN wiki_sources ws ON ws.source_id = wps.source_id
            WHERE wps.page_id = ? AND ws.status = 'active'
            ORDER BY ws.title, wps.locator
            """,
            (page_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _pages(connection, page_ids: set[str]) -> list[dict]:
        if not page_ids:
            return []
        placeholders = ",".join("?" for _ in page_ids)
        rows = connection.execute(
            f"SELECT * FROM wiki_pages WHERE page_id IN ({placeholders})",
            tuple(sorted(page_ids)),
        ).fetchall()
        return [dict(row) for row in rows]

    def _index_page(self, connection, page_id: str) -> None:
        row = connection.execute(
            "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
        ).fetchone()
        self._delete_fts(connection, page_id)
        if row is None or str(row["status"]) != "active":
            return
        connection.execute(
            """
            INSERT INTO wiki_pages_fts (
                page_id, canonical_title, summary, body_markdown
            ) VALUES (?, ?, ?, ?)
            """,
            (
                page_id,
                self._tokenize(str(row["canonical_title"])),
                self._tokenize(str(row["summary"])),
                self._tokenize(str(row["body_markdown"])),
            ),
        )

    @staticmethod
    def _delete_fts(connection, page_id: str) -> None:
        connection.execute("DELETE FROM wiki_pages_fts WHERE page_id = ?", (page_id,))

    @staticmethod
    def _tokenize(text: str) -> str:
        return " ".join(item.strip() for item in jieba.lcut(text) if item.strip())

    @staticmethod
    def _normalize_alias(value: str) -> str:
        return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)

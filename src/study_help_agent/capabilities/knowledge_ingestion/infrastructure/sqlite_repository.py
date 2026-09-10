"""以一个 SQLite 事务保存资产并写入 Outbox，避免双写不一致。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from study_help_agent.infrastructure.persistence.sqlite import SqliteConnectionFactory
from study_help_agent.runtime.serialization import to_serializable
from .lexical_index_writer import LexicalTextEncoder

from ..application.ports import KnowledgeIngestionRepository
from ..domain.enums import IngestionStatus, KnowledgeAssetType, KnowledgeSpace
from ..domain.hashing import (
    content_digest,
    stable_asset_id,
    stable_deletion_job_id,
    stable_job_id,
)
from ..domain.models import (
    IngestionJob,
    IngestionReceipt,
    KnowledgeAsset,
    KnowledgeAssetDraft,
    KnowledgeChunk,
    utc_now,
)


class SqliteKnowledgeIngestionRepository(KnowledgeIngestionRepository):
    """实现资产幂等、版本递增和 Transactional Outbox。"""

    def __init__(self, connections: SqliteConnectionFactory) -> None:
        self._connections = connections
        self._lexical_encoder = LexicalTextEncoder()

    def upsert_and_enqueue(self, draft: KnowledgeAssetDraft) -> IngestionReceipt:
        """同一来源内容未变化则跳过，否则原子更新资产并创建任务。"""

        digest = content_digest(draft.content)
        asset_id = stable_asset_id(
            space=draft.space.value,
            stable_source_key=draft.stable_source_key,
        )
        now = utc_now().isoformat()
        metadata_json = json.dumps(
            to_serializable(dict(draft.metadata)),
            ensure_ascii=False,
            sort_keys=True,
        )

        with self._connections.connect() as connection:
            existing = connection.execute(
                """
                SELECT content_hash, version
                FROM knowledge_assets
                WHERE asset_id = ?
                """,
                (asset_id,),
            ).fetchone()
            if existing is not None and existing["content_hash"] == digest:
                return IngestionReceipt(
                    asset_id=asset_id,
                    job_id=None,
                    created=False,
                    skipped_reason="content_unchanged",
                )

            version = 1 if existing is None else int(existing["version"]) + 1
            connection.execute(
                """
                INSERT INTO knowledge_assets (
                    asset_id, space, asset_type, stable_source_key,
                    title, content, content_hash, version, status,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    asset_type = excluded.asset_type,
                    title = excluded.title,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    version = excluded.version,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    asset_id,
                    draft.space.value,
                    draft.asset_type.value,
                    draft.stable_source_key,
                    draft.title,
                    draft.content,
                    digest,
                    version,
                    IngestionStatus.PENDING.value,
                    metadata_json,
                    now,
                    now,
                ),
            )
            job_id = stable_job_id(
                asset_id=asset_id,
                version=version,
                content_hash=digest,
            )
            connection.execute(
                """
                INSERT INTO ingestion_outbox (
                    job_id, asset_id, asset_version, event_type, status,
                    attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    job_id,
                    asset_id,
                    version,
                    "knowledge_asset.ready",
                    IngestionStatus.PENDING.value,
                    now,
                    now,
                ),
            )
        return IngestionReceipt(asset_id=asset_id, job_id=job_id, created=True)

    def get_asset_record(self, asset_id: str) -> dict[str, Any] | None:
        """读取资产原始记录，供诊断、后续 Worker 和测试使用。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def list_pending_jobs(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        """按创建顺序读取待处理任务，为第三阶段 Worker 提供稳定入口。"""

        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM ingestion_outbox
                WHERE status IN (?, ?)
                ORDER BY created_at, job_id
                LIMIT ?
                """,
                (
                    IngestionStatus.PENDING.value,
                    IngestionStatus.RETRYING.value,
                    limit,
                ),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def index_revision(self) -> str:
        """返回已完成知识索引的轻量版本戳，用于让 RAG 缓存自动失效。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS asset_count,
                       COALESCE(MAX(updated_at), '') AS latest_update,
                       COALESCE(SUM(version), 0) AS version_sum
                FROM knowledge_assets
                WHERE status = ?
                """,
                (IngestionStatus.COMPLETED.value,),
            ).fetchone()
        return f"{row['asset_count']}:{row['latest_update']}:{row['version_sum']}"

    def request_delete_by_source_key(self, stable_source_key: str) -> int:
        """按完整业务来源键创建可靠删除任务。"""

        return self._request_delete("stable_source_key = ?", (stable_source_key,))

    def request_delete_by_source_prefix(self, source_prefix: str) -> int:
        """按项目来源前缀批量创建报告和代码块删除任务。"""

        escaped = source_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self._request_delete(
            "stable_source_key LIKE ? ESCAPE '\\'", (f"{escaped}%",)
        )

    def _request_delete(self, where_sql: str, parameters: tuple[Any, ...]) -> int:
        """立即移除 FTS/规范 Chunk，并原子写入 Qdrant 删除 Outbox。"""

        now = utc_now().isoformat()
        with self._connections.connect() as connection:
            rows = connection.execute(
                f"SELECT asset_id, version FROM knowledge_assets WHERE {where_sql}",
                parameters,
            ).fetchall()
            for row in rows:
                asset_id, version = str(row["asset_id"]), int(row["version"])
                connection.execute(
                    "DELETE FROM knowledge_chunks_fts WHERE asset_id = ?", (asset_id,)
                )
                connection.execute(
                    "DELETE FROM knowledge_chunks WHERE asset_id = ?", (asset_id,)
                )
                connection.execute(
                    "UPDATE knowledge_assets SET status = ?, updated_at = ? WHERE asset_id = ?",
                    (IngestionStatus.DELETING.value, now, asset_id),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ingestion_outbox (
                        job_id, asset_id, asset_version, event_type, status,
                        attempt_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        stable_deletion_job_id(asset_id=asset_id, version=version),
                        asset_id,
                        version,
                        "knowledge_asset.deleted",
                        IngestionStatus.PENDING.value,
                        now,
                        now,
                    ),
                )
        return len(rows)

    def claim_jobs(self, *, limit: int) -> tuple[IngestionJob, ...]:
        """以状态条件更新的方式领取任务，避免同一任务被两个 Worker 同时处理。"""

        now = utc_now().isoformat()
        claimed: list[IngestionJob] = []
        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM ingestion_outbox
                WHERE status IN (?, ?)
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at, job_id
                LIMIT ?
                """,
                (IngestionStatus.PENDING.value, IngestionStatus.RETRYING.value, now, limit),
            ).fetchall()
            for row in rows:
                changed = connection.execute(
                    """
                    UPDATE ingestion_outbox
                    SET status = ?, updated_at = ?
                    WHERE job_id = ? AND status IN (?, ?)
                    """,
                    (
                        IngestionStatus.PROCESSING.value,
                        now,
                        row["job_id"],
                        IngestionStatus.PENDING.value,
                        IngestionStatus.RETRYING.value,
                    ),
                ).rowcount
                if changed:
                    claimed.append(self._job_from_row(row))
        return tuple(claimed)

    def get_asset(self, asset_id: str) -> KnowledgeAsset | None:
        """把 SQLite 记录还原成 Worker 可处理的领域资产。"""

        record = self.get_asset_record(asset_id)
        if record is None:
            return None
        return KnowledgeAsset(
            asset_id=str(record["asset_id"]),
            space=KnowledgeSpace(record["space"]),
            asset_type=KnowledgeAssetType(record["asset_type"]),
            stable_source_key=str(record["stable_source_key"]),
            title=str(record["title"]),
            content=str(record["content"]),
            content_hash=str(record["content_hash"]),
            version=int(record["version"]),
            status=IngestionStatus(record["status"]),
            metadata=json.loads(record["metadata_json"]),
            created_at=datetime.fromisoformat(record["created_at"]),
            updated_at=datetime.fromisoformat(record["updated_at"]),
        )

    def replace_chunks(
        self, asset: KnowledgeAsset, chunks: Sequence[KnowledgeChunk]
    ) -> None:
        """原子替换资产的规范切块及 FTS5 关键词索引。"""

        now = utc_now().isoformat()
        with self._connections.connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_chunks_fts WHERE asset_id = ?", (asset.asset_id,)
            )
            connection.execute(
                "DELETE FROM knowledge_chunks WHERE asset_id = ?", (asset.asset_id,)
            )
            for chunk in chunks:
                metadata_json = json.dumps(
                    to_serializable(dict(chunk.metadata)), ensure_ascii=False, sort_keys=True
                )
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        chunk_id, asset_id, asset_version, space, chunk_index,
                        logical_key, content, content_hash, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.asset_id,
                        chunk.asset_version,
                        chunk.space.value,
                        chunk.chunk_index,
                        chunk.logical_key,
                        chunk.content,
                        chunk.content_hash,
                        metadata_json,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks_fts (
                        chunk_id, asset_id, space, title, content
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        asset.asset_id,
                        asset.space.value,
                        self._lexical_encoder.encode(asset.title),
                        self._lexical_encoder.encode(chunk.content),
                    ),
                )

    def search_lexical(
        self, query: str, *, spaces: Sequence[KnowledgeSpace], limit: int = 20
    ) -> tuple[dict[str, Any], ...]:
        """使用 jieba 分词后的 FTS5 增量索引执行关键词召回。"""

        terms = list(self._lexical_encoder.terms(query))
        if not terms or not spaces:
            return ()
        match_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        placeholders = ",".join("?" for _ in spaces)
        sql = f"""
            SELECT c.*, a.title AS asset_title, a.asset_type,
                   bm25(knowledge_chunks_fts) AS lexical_score
            FROM knowledge_chunks_fts
            JOIN knowledge_chunks c
              ON c.chunk_id = knowledge_chunks_fts.chunk_id
            JOIN knowledge_assets a
              ON a.asset_id = c.asset_id
            WHERE knowledge_chunks_fts MATCH ?
              AND c.space IN ({placeholders})
            ORDER BY lexical_score
            LIMIT ?
        """
        with self._connections.connect() as connection:
            rows = connection.execute(
                sql,
                (match_query, *(space.value for space in spaces), limit),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def mark_completed(self, job_id: str, asset_id: str) -> None:
        """只有向量与关键词索引都成功后才把任务和资产标为完成。"""

        now = utc_now().isoformat()
        with self._connections.connect() as connection:
            connection.execute(
                "UPDATE ingestion_outbox SET status = ?, updated_at = ?, last_error = NULL WHERE job_id = ?",
                (IngestionStatus.COMPLETED.value, now, job_id),
            )
            connection.execute(
                "UPDATE knowledge_assets SET status = ?, updated_at = ? WHERE asset_id = ?",
                (IngestionStatus.COMPLETED.value, now, asset_id),
            )

    def mark_superseded(self, job_id: str) -> None:
        """旧版本任务没有对应内容快照时标记为被新版本替代。"""

        with self._connections.connect() as connection:
            connection.execute(
                "UPDATE ingestion_outbox SET status = ?, updated_at = ? WHERE job_id = ?",
                (IngestionStatus.SUPERSEDED.value, utc_now().isoformat(), job_id),
            )

    def finalize_delete(self, asset_id: str) -> None:
        """Qdrant 删除成功后删除规范资产，外键会清理该资产的全部 Outbox。"""

        with self._connections.connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_chunks_fts WHERE asset_id = ?", (asset_id,)
            )
            connection.execute("DELETE FROM knowledge_assets WHERE asset_id = ?", (asset_id,))

    def mark_failed(self, job_id: str, error: str, *, max_attempts: int) -> None:
        """记录错误并按指数退避重试，超过上限后进入 failed。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT attempt_count FROM ingestion_outbox WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempt_count"]) + 1
            terminal = attempts >= max_attempts
            delay_seconds = min(1800, 30 * (2 ** max(0, attempts - 1)))
            retry_at = None if terminal else (utc_now() + timedelta(seconds=delay_seconds)).isoformat()
            connection.execute(
                """
                UPDATE ingestion_outbox
                SET status = ?, attempt_count = ?, next_retry_at = ?,
                    last_error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    IngestionStatus.FAILED.value if terminal else IngestionStatus.RETRYING.value,
                    attempts,
                    retry_at,
                    error[:4000],
                    utc_now().isoformat(),
                    job_id,
                ),
            )

    def recover_processing_jobs(self) -> int:
        """应用重启时把未完成的 processing 任务恢复为 retrying。"""

        with self._connections.connect() as connection:
            return connection.execute(
                """
                UPDATE ingestion_outbox
                SET status = ?, next_retry_at = NULL, updated_at = ?
                WHERE status = ?
                """,
                (
                    IngestionStatus.RETRYING.value,
                    utc_now().isoformat(),
                    IngestionStatus.PROCESSING.value,
                ),
            ).rowcount

    @staticmethod
    def _job_from_row(row: Any) -> IngestionJob:
        """将 SQLite Row 转换成领域任务。"""

        return IngestionJob(
            job_id=str(row["job_id"]),
            asset_id=str(row["asset_id"]),
            asset_version=int(row["asset_version"]),
            event_type=str(row["event_type"]),
            status=IngestionStatus.PROCESSING,
            attempt_count=int(row["attempt_count"]),
            next_retry_at=(
                datetime.fromisoformat(row["next_retry_at"])
                if row["next_retry_at"]
                else None
            ),
            last_error=row["last_error"],
        )

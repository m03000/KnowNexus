"""外部智能体监听统计的 SQLite 持久化。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class WatcherStatisticsStore:
    """以五分钟桶低频保存统计，不保存任何对话正文。"""

    def __init__(self, database) -> None:
        self.database = database

    def append(self, *, watcher_id: str, watcher_name: str, active_seconds: int,
               captured_turns: int, duplicate_turns: int, distillation_tokens: int,
               scan_count: int, error_count: int, sessions: set[str]) -> None:
        now = datetime.now(timezone.utc)
        minute = now.minute - now.minute % 5
        bucket = now.replace(minute=minute, second=0, microsecond=0).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO watcher_monitor_buckets (
                    watcher_id, watcher_name, bucket_start, active_seconds,
                    captured_turns, duplicate_turns, distillation_tokens,
                    scan_count, error_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(watcher_id, bucket_start) DO UPDATE SET
                    watcher_name=excluded.watcher_name,
                    active_seconds=active_seconds + excluded.active_seconds,
                    captured_turns=captured_turns + excluded.captured_turns,
                    duplicate_turns=duplicate_turns + excluded.duplicate_turns,
                    distillation_tokens=distillation_tokens + excluded.distillation_tokens,
                    scan_count=scan_count + excluded.scan_count,
                    error_count=error_count + excluded.error_count
                """,
                (watcher_id, watcher_name, bucket, max(0, active_seconds),
                 max(0, captured_turns), max(0, duplicate_turns),
                 max(0, distillation_tokens), max(0, scan_count), max(0, error_count)),
            )
            for session_id in sessions:
                connection.execute(
                    """INSERT OR IGNORE INTO watcher_monitor_sessions
                       (watcher_id, external_session_id, bucket_start) VALUES (?, ?, ?)""",
                    (watcher_id, session_id, bucket),
                )

    def query(self, *, start_at: str = "", end_at: str = "") -> dict[str, dict[str, Any]]:
        where, parameters = [], []
        if start_at:
            where.append("bucket_start >= ?")
            parameters.append(start_at)
        if end_at:
            where.append("bucket_start < ?")
            parameters.append(end_at)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        session_where = clause
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""SELECT watcher_id, MAX(watcher_name) watcher_name,
                    SUM(active_seconds) active_seconds,
                    SUM(captured_turns) captured_turns,
                    SUM(duplicate_turns) duplicate_turns,
                    SUM(distillation_tokens) distillation_tokens,
                    SUM(scan_count) scan_count, SUM(error_count) error_count,
                    MAX(bucket_start) last_saved_at
                    FROM watcher_monitor_buckets {clause} GROUP BY watcher_id""",
                parameters,
            ).fetchall()
            session_rows = connection.execute(
                f"""SELECT watcher_id, COUNT(DISTINCT external_session_id) conversation_count
                    FROM watcher_monitor_sessions {session_where} GROUP BY watcher_id""",
                parameters,
            ).fetchall()
        result = {str(row["watcher_id"]): dict(row) for row in rows}
        for row in session_rows:
            result.setdefault(str(row["watcher_id"]), {})["conversation_count"] = int(row["conversation_count"])
        return result

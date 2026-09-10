"""Codex Hook 的本地失败暂存队列。

Hook 是短生命周期子进程，不依赖内存共享。用一个独立的小型 SQLite
数据库拼接 UserPromptSubmit 与 Stop 事件；后端暂时不可用时，完整轮次仍留在队列中。
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SpoolTurn:
    """暂存队列中可投递的一条完整 Codex 轮次。"""

    session_id: str
    turn_id: str
    prompt: str
    assistant_message: str
    cwd: str
    model: str
    transcript_path: str
    metadata: dict[str, Any]


def default_spool_path() -> Path:
    """返回用户级 Hook 队列位置，可由环境变量覆盖。"""

    configured = os.getenv("PERSONAL_AGENT_CAPTURE_SPOOL", "").strip()
    if configured:
        return Path(configured).expanduser()
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return root / "personal_agent" / "codex_capture_spool.db"


class HookSpool:
    """提供事件 UPSERT、完整轮次读取和确认删除的最小持久队列。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_spool_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record_prompt(self, payload: dict[str, Any]) -> None:
        """保存用户输入；若 Stop 先到达，UPSERT 会保留已有回复。"""

        session_id, turn_id = self._ids(payload)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_turns
                       (session_id, turn_id, prompt, cwd, model, transcript_path,
                        metadata_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(session_id, turn_id) DO UPDATE SET
                       prompt = excluded.prompt, cwd = excluded.cwd,
                       model = excluded.model,
                       transcript_path = excluded.transcript_path,
                       metadata_json = excluded.metadata_json,
                       updated_at = datetime('now')""",
                (
                    session_id, turn_id, str(payload.get("prompt") or ""),
                    str(payload.get("cwd") or ""), str(payload.get("model") or ""),
                    str(payload.get("transcript_path") or ""),
                    json.dumps(self._metadata(payload), ensure_ascii=False),
                ),
            )

    def record_stop(self, payload: dict[str, Any]) -> None:
        """保存最终助手回复；不读取推理过程或工具内部输出。"""

        session_id, turn_id = self._ids(payload)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_turns
                       (session_id, turn_id, assistant_message, cwd, model,
                        transcript_path, metadata_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(session_id, turn_id) DO UPDATE SET
                       assistant_message = excluded.assistant_message,
                       cwd = CASE WHEN excluded.cwd != '' THEN excluded.cwd ELSE cwd END,
                       model = CASE WHEN excluded.model != '' THEN excluded.model ELSE model END,
                       transcript_path = CASE WHEN excluded.transcript_path != ''
                           THEN excluded.transcript_path ELSE transcript_path END,
                       updated_at = datetime('now')""",
                (
                    session_id, turn_id,
                    str(payload.get("last_assistant_message") or ""),
                    str(payload.get("cwd") or ""), str(payload.get("model") or ""),
                    str(payload.get("transcript_path") or ""),
                    json.dumps(self._metadata(payload), ensure_ascii=False),
                ),
            )

    def ready(self, *, limit: int = 50) -> tuple[SpoolTurn, ...]:
        """读取用户输入和助手回复均已到齐且尚未确认的轮次。"""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM pending_turns
                   WHERE prompt != '' AND assistant_message != ''
                   ORDER BY updated_at LIMIT ?""",
                (limit,),
            ).fetchall()
        return tuple(
            SpoolTurn(
                session_id=str(row["session_id"]), turn_id=str(row["turn_id"]),
                prompt=str(row["prompt"]),
                assistant_message=str(row["assistant_message"]),
                cwd=str(row["cwd"]), model=str(row["model"]),
                transcript_path=str(row["transcript_path"]),
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        )

    def acknowledge(self, turn: SpoolTurn) -> None:
        """仅在服务端成功响应后删除队列记录，形成至少一次投递。"""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM pending_turns WHERE session_id = ? AND turn_id = ?",
                (turn.session_id, turn.turn_id),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS pending_turns (
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    assistant_message TEXT NOT NULL DEFAULT '',
                    cwd TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    transcript_path TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (session_id, turn_id)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=3)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 3000")
        return connection

    @staticmethod
    def _ids(payload: dict[str, Any]) -> tuple[str, str]:
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        if not session_id or not turn_id:
            raise ValueError("Codex Hook 缺少 session_id 或 turn_id")
        return session_id, turn_id

    @staticmethod
    def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "hook_event_name": payload.get("hook_event_name", ""),
            "stop_hook_active": bool(payload.get("stop_hook_active", False)),
            "capture_source": payload.get("capture_source", "codex_hook"),
            "completed_at": payload.get("completed_at"),
            "duration_ms": payload.get("duration_ms"),
            "codex_thread_source": payload.get("codex_thread_source", ""),
            "codex_session_source": payload.get("codex_session_source", ""),
        }

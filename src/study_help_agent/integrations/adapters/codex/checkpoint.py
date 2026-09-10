"""Codex 适配器的持久化读取检查点。

SQLite 只保存每个 rollout 文件已安全转存到 HookSpool 的字节位置。进程重启后
可以从最近完成轮次继续；重复读取也会被 (session_id, turn_id) 幂等键吸收。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def default_checkpoint_path() -> Path:
    """返回用户级监听检查点位置，允许环境变量覆盖。"""

    configured = os.getenv("PERSONAL_AGENT_CODEX_CHECKPOINT", "").strip()
    if configured:
        return Path(configured).expanduser()
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return root / "personal_agent" / "codex_watcher_checkpoint.db"


class CaptureCheckpoint:
    """按规范化文件路径保存最后一个完整轮次后的字节偏移量。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_checkpoint_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS file_offsets (
                    path TEXT PRIMARY KEY,
                    offset INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    def get(self, path: Path) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT offset FROM file_offsets WHERE path = ?", (str(path.resolve()),)
            ).fetchone()
        return None if row is None else int(row[0])

    def set(self, path: Path, offset: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO file_offsets(path, offset, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(path) DO UPDATE SET
                       offset = excluded.offset, updated_at = datetime('now')""",
                (str(path.resolve()), max(0, int(offset))),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=3)
        connection.execute("PRAGMA busy_timeout = 3000")
        return connection

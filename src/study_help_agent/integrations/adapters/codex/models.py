"""Codex 会话适配器的内部数据模型。

这些模型把不稳定的 Codex JSONL 字段隔离在集成边界内，避免记忆业务层直接
依赖 Codex 的本地存储格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CapturedTurn:
    """从一次已完成的 Codex task 中提取出的用户—助手对话轮次。"""

    session_id: str
    turn_id: str
    prompt: str
    assistant_message: str
    cwd: str = ""
    model: str = ""
    transcript_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def prompt_event(self) -> dict[str, Any]:
        """转换为现有 HookSpool 能接收的用户事件。"""

        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "prompt": self.prompt,
            "cwd": self.cwd,
            "model": self.model,
            "transcript_path": self.transcript_path,
            **self.metadata,
        }

    def stop_event(self) -> dict[str, Any]:
        """转换为现有 HookSpool 能接收的助手完成事件。"""

        return {
            "hook_event_name": "Stop",
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "last_assistant_message": self.assistant_message,
            "cwd": self.cwd,
            "model": self.model,
            "transcript_path": self.transcript_path,
            **self.metadata,
        }


@dataclass(slots=True)
class FileRuntime:
    """监听进程内某个 JSONL 文件的增量读取状态。"""

    path: Path
    offset: int
    parser: Any

"""外部智能体对话接入的领域模型。

本文件只表达“外部会话、外部轮次和捕获结果”这些业务概念，不依赖
FastAPI、Codex Hooks 或 SQLite，因此其它智能体客户端也能复用同一套模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


OriginType = Literal["internal", "external"]


@dataclass(frozen=True, slots=True)
class ExternalConversationTurn:
    """一轮已经完成的外部对话；用户输入与最终助手回复必须同时存在。"""

    client: str
    external_session_id: str
    external_turn_id: str
    user_message: str
    assistant_message: str
    title: str = ""
    cwd: str = ""
    model: str = ""
    transcript_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """捕获命令的稳定结果，供 HTTP、MCP 和 Hook 三种入口共同返回。"""

    session_id: str
    turn_id: str
    duplicate: bool
    user_message_id: int
    assistant_message_id: int
    consolidation: dict[str, Any] = field(default_factory=dict)

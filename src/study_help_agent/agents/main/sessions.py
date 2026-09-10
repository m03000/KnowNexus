"""提供主 Agent 对话会话的轻量内存存储。

Loop 的单次运行状态与跨请求会话是两个概念。本文件只保存经过裁剪的用户/助手文本，
让同一 session_id 的下一次请求获得必要上下文；大型产物仍通过 Artifact Store 传递。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """保存一条经过裁剪的会话消息。"""

    role: str
    content: str


class InMemoryConversationStore:
    """线程安全地保存最近若干条会话消息。"""

    def __init__(self, *, max_messages: int = 12, max_characters: int = 24_000) -> None:
        """设置每个会话的消息数量和字符预算。"""

        if max_messages < 1 or max_characters < 1:
            raise ValueError("Conversation limits must be positive")
        self._max_messages = max_messages
        self._max_characters = max_characters
        self._sessions: dict[str, list[ConversationMessage]] = {}
        self._lock = RLock()

    def history(self, session_id: str) -> tuple[ConversationMessage, ...]:
        """读取指定会话的不可变历史快照。"""

        with self._lock:
            return tuple(self._sessions.get(session_id, ()))

    def append(self, session_id: str, *, role: str, content: str) -> None:
        """追加消息并按数量和总字符预算裁剪旧内容。"""

        message = ConversationMessage(role=role.strip(), content=content.strip())
        if not message.role or not message.content:
            return
        with self._lock:
            messages = self._sessions.setdefault(session_id, [])
            messages.append(message)
            messages[:] = messages[-self._max_messages :]
            while len(messages) > 1 and sum(len(item.content) for item in messages) > self._max_characters:
                messages.pop(0)

    def build_goal(self, session_id: str, current_message: str) -> str:
        """把近期对话和当前请求组合成一次 Loop 的明确目标。"""

        history = self.history(session_id)
        if not history:
            return current_message
        lines = ["以下是同一会话的近期上下文，仅作为用户目标背景："]
        lines.extend(f"{item.role}: {item.content}" for item in history)
        lines.extend(("", "当前用户请求：", current_message))
        return "\n".join(lines)

    def recent_message_ids(self, session_id: str, *, limit: int = 2) -> list[int]:
        """内存实现无持久化 message_id，返回空列表（蒸馏溯源仅 SQLite 路径使用）。"""

        return []

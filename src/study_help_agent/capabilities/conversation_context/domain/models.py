"""短期会话记忆的纯领域模型，不依赖数据库或 LLM。"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SessionMessage:
    """用于构建当前上下文的一条原始会话消息。"""

    message_id: int
    role: str
    content: str
    created_at: str
    origin_type: str = "internal"
    origin_client: str = "personal_agent"


@dataclass(frozen=True, slots=True)
class ActiveTaskContext:
    """当前会话仍在推进的任务状态。"""

    active_goal: str = ""
    completed_steps: tuple[str, ...] = ()
    pending_steps: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationContextSnapshot:
    """一次会话当前可供 Agent 使用的短期记忆快照。"""

    session_id: str
    summary: str = ""
    summary_until_message_id: int = 0
    distilled_until_message_id: int = 0
    messages: tuple[SessionMessage, ...] = ()
    active_context: ActiveTaskContext = field(default_factory=ActiveTaskContext)


@dataclass(frozen=True, slots=True)
class SavedTurn:
    """原子保存一轮对话后返回的消息位置。"""

    session_id: str
    turn_id: str
    user_message_id: int
    assistant_message_id: int

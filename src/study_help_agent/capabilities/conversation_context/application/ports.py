"""短期记忆应用层端口。"""

from typing import Any, Protocol

from study_help_agent.capabilities.conversation_context.domain.models import (
    ActiveTaskContext,
    SavedTurn,
    ConversationContextSnapshot,
    SessionMessage,
)


class ConversationContextRepository(Protocol):
    """短期记忆服务需要的最小持久化接口。"""

    def get_context_snapshot(
        self,
        session_id: str,
        *,
        recent_message_limit: int,
    ) -> ConversationContextSnapshot:
        ...

    def save_turn(
        self,
        session_id: str,
        *,
        turn_id: str,
        user_message: str,
        assistant_message: str,
        origin_type: str = "internal",
        origin_client: str = "personal_agent",
        external_session_id: str | None = None,
        external_turn_id: str | None = None,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SavedTurn:
        ...

    def get_saved_turn(self, session_id: str, *, turn_id: str) -> SavedTurn:
        ...

    def list_messages_after(
        self,
        session_id: str,
        *,
        after_message_id: int,
        limit: int,
    ) -> tuple[SessionMessage, ...]:
        ...

    def update_summary(
        self,
        session_id: str,
        *,
        summary: str,
        summary_until_message_id: int,
    ) -> None:
        ...

    def update_active_context(
        self,
        session_id: str,
        context: ActiveTaskContext,
    ) -> None:
        ...

    def update_distillation_cursor(
        self,
        session_id: str,
        *,
        distilled_until_message_id: int,
    ) -> None:
        ...

    def get_recorded_turn(
        self, session_id: str, *, turn_id: str,
    ) -> tuple[str, str] | None:
        ...

    def acquire_lease(
        self, session_id: str, *, purpose: str, owner_id: str,
        ttl_seconds: int = 300,
    ) -> bool:
        ...

    def release_lease(
        self, session_id: str, *, purpose: str, owner_id: str,
    ) -> None:
        ...

    def list_internal_sessions(self, *, limit: int = 50) -> tuple[dict[str, Any], ...]: ...

    def list_session_messages(
        self, session_id: str, *, limit: int = 500,
    ) -> tuple[SessionMessage, ...]: ...

    def delete_internal_session(self, session_id: str) -> bool: ...
    def rename_session(self, session_id: str, *, title: str) -> bool: ...
    def create_internal_session(
        self, session_id: str, *, title: str = "新对话",
    ) -> dict[str, Any]:
        """立即创建一个可被刷新恢复的网页内部会话。"""
        ...

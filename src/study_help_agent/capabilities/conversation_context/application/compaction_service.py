"""对超出预算的历史消息执行滚动摘要。"""

from uuid import uuid4

from study_help_agent.capabilities.conversation_context.application.ports import (
    ConversationContextRepository,
)
from study_help_agent.capabilities.conversation_context.application.token_budget import (
    ContextBudget,
)
from study_help_agent.capabilities.conversation_context.llm.operations import (
    ConversationSummaryOperations,
)


class SessionCompactionService:
    def __init__(
        self,
        *,
        repository: ConversationContextRepository,
        operations: ConversationSummaryOperations,
        budget: ContextBudget,
        preserve_recent_messages: int = 6,
    ) -> None:
        self._repository = repository
        self._operations = operations
        self._budget = budget
        self._preserve_recent_messages = (
            preserve_recent_messages
        )

    def compact_if_needed(
        self,
        session_id: str,
    ) -> bool:
        owner_id = uuid4().hex
        if not self._repository.acquire_lease(
            session_id, purpose="short_compaction", owner_id=owner_id
        ):
            return False
        try:
            return self._compact(session_id)
        finally:
            self._repository.release_lease(
                session_id, purpose="short_compaction", owner_id=owner_id
            )

    def _compact(self, session_id: str) -> bool:
        """在已取得会话压缩租约后执行一次滚动摘要。"""
        memory = self._repository.get_context_snapshot(
            session_id,
            recent_message_limit=100,
        )

        if not self._budget.requires_compaction(
            memory.messages
        ):
            return False

        if len(memory.messages) <= self._preserve_recent_messages:
            return False

        old_messages = memory.messages[
            :-self._preserve_recent_messages
        ]

        messages_text = "\n".join(
            f"{message.role}: {message.content}"
            for message in old_messages
        )

        summary = self._operations.summarize(
            previous_summary=memory.summary,
            messages_text=messages_text,
        )

        self._repository.update_summary(
            session_id,
            summary=summary,
            summary_until_message_id=(
                old_messages[-1].message_id
            ),
        )

        return True

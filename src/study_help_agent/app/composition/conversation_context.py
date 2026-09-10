"""组装短期会话记忆的仓储、预算、摘要器与应用门面。"""

from dataclasses import dataclass

from study_help_agent.capabilities.conversation_context.application.compaction_service import SessionCompactionService
from study_help_agent.capabilities.conversation_context.application.context_service import SessionContextService
from study_help_agent.capabilities.conversation_context.application.service import ConversationContextService
from study_help_agent.capabilities.conversation_context.application.token_budget import ContextBudget
from study_help_agent.capabilities.conversation_context.infrastructure.sqlite_repository import SqliteConversationContextRepository
from study_help_agent.capabilities.conversation_context.llm.operations import ConversationSummaryOperations


@dataclass(frozen=True, slots=True)
class ConversationContextComposition:
    service: ConversationContextService
    repository: SqliteConversationContextRepository


def compose_conversation_context(*, llm, database) -> ConversationContextComposition:
    repository = SqliteConversationContextRepository(database)
    budget = ContextBudget(max_messages=12, max_characters=24_000,
                           compaction_trigger_characters=18_000)
    context_service = SessionContextService(
        repository=repository, recent_message_limit=12, max_characters=24_000
    )
    compaction_service = SessionCompactionService(
        repository=repository,
        operations=ConversationSummaryOperations(llm),
        budget=budget,
        preserve_recent_messages=6,
    )
    return ConversationContextComposition(
        service=ConversationContextService(
            repository=repository,
            context_service=context_service,
            compaction_service=compaction_service,
        ),
        repository=repository,
    )

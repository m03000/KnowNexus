from typing import Protocol

from study_help_agent.capabilities.long_term_memory import MemoryPoint


class ConsolidationRepository(Protocol):
    def acquire_lease(
        self, session_id: str, *, purpose: str, owner_id: str,
        ttl_seconds: int = 300,
    ) -> bool:
        ...

    def release_lease(
        self, session_id: str, *, purpose: str, owner_id: str,
    ) -> None:
        ...

    def pending_messages(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ):
        ...

    def update_distillation_cursor(
        self,
        session_id: str,
        *,
        message_id: int,
    ) -> None:
        ...


class RelatedMemoryProvider(Protocol):
    def search(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[MemoryPoint, ...]:
        ...

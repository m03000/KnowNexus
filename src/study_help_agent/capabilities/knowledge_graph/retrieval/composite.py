from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class GraphRetriever(Protocol):
    def retrieve(
        self,
        *,
        query: str,
        limit: int,
        spaces: tuple[str, ...],
    ) -> list[RetrievedChunk]:
        ...


class CompositeGraphRetriever:
    def __init__(
        self,
        *,
        project_retriever=None,
        memory_retriever=None,
        personal_retriever=None,
    ) -> None:
        self._project = project_retriever
        self._memory = memory_retriever
        self._personal = personal_retriever

    def retrieve(
        self,
        *,
        query: str,
        limit: int,
        spaces: tuple[str, ...],
    ) -> list[RetrievedChunk]:
        results: list[RetrievedChunk] = []

        if "project_code" in spaces and self._project is not None:
            results.extend(
                self._project.retrieve(
                    query=query,
                    limit=limit,
                )
            )

        if "user_memory" in spaces and self._memory is not None:
            results.extend(
                self._memory.retrieve(
                    query=query,
                    limit=limit,
                )
            )

        if "personal_knowledge" in spaces and self._personal is not None:
            results.extend(
                self._personal.retrieve(
                    query=query,
                    limit=limit,
                )
            )

        return results[:limit]

"""对话记忆 Capability 的依赖组合模块。"""

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.capabilities.long_term_memory import (
    MemoryDistiller,
    MemorySearchIndexer,
    SqliteMemoryStore,
)
from study_help_agent.capabilities.long_term_memory.consolidation_policy import MemoryConsolidationPolicy
from study_help_agent.capabilities.long_term_memory.consolidation_service import MemoryConsolidationService
from study_help_agent.capabilities.knowledge_ingestion.infrastructure import (
    SqliteKnowledgeIngestionRepository,
)
from study_help_agent.infrastructure.persistence import SqliteConnectionFactory


@dataclass(frozen=True, slots=True)
class LongTermMemoryComposition:
    store: SqliteMemoryStore
    distiller: MemoryDistiller
    consolidation: MemoryConsolidationService
    search_indexer: MemorySearchIndexer


def compose_long_term_memory(
    *,
    llm: BaseChatModel,
    database: SqliteConnectionFactory,
    knowledge_repository: SqliteKnowledgeIngestionRepository,
    consolidation_repository,
) -> LongTermMemoryComposition:
    store = SqliteMemoryStore(connections=database)
    indexer = MemorySearchIndexer(repository=knowledge_repository)
    distiller = MemoryDistiller(
        llm=llm,
        memory_store=store,
        search_indexer=indexer,
    )
    return LongTermMemoryComposition(
        store=store,
        distiller=distiller,
        consolidation=MemoryConsolidationService(
            repository=consolidation_repository,
            policy=MemoryConsolidationPolicy(max_pending_turns=3),
            distiller=distiller,
            related_memories=store,
        ),
        search_indexer=indexer,
    )

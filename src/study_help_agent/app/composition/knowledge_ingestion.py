"""组装知识自动入库的 Projector、事务仓储、协调器和 Runtime Hook。"""

from dataclasses import dataclass

from study_help_agent.capabilities.knowledge_ingestion.application.coordinator import (
    KnowledgeIngestionCoordinator,
)
from study_help_agent.capabilities.knowledge_ingestion.application.indexing_service import (
    KnowledgeIndexingService,
)
from study_help_agent.capabilities.knowledge_ingestion.application.deletion_service import (
    KnowledgeDeletionService,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.enums import KnowledgeSpace
from study_help_agent.capabilities.knowledge_ingestion.application.projectors import (
    ArtifactProjectorRegistry,
    CodeAnalysisProjector,
    LearningNoteProjector,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.policies import (
    AutoIngestionPolicy,
)
from study_help_agent.capabilities.knowledge_ingestion.infrastructure import (
    SqliteKnowledgeIngestionRepository,
    KnowledgeIngestionWorker,
    QdrantKnowledgeIndexWriter,
)
from study_help_agent.capabilities.knowledge_ingestion.infrastructure.chunkers import (
    AssetChunkerRouter,
)
from study_help_agent.capabilities.rag.infrastructure.embeddings import (
    SentenceTransformerEmbedder,
)
from study_help_agent.core.config import Settings
from study_help_agent.infrastructure.persistence.sqlite import SqliteConnectionFactory
from study_help_agent.infrastructure.search import LocalQdrantClientProvider
from study_help_agent.capabilities.knowledge_ingestion.infrastructure.runtime_hook import (
    AutoIngestionHook,
)


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionComposition:
    """暴露启动组合根需要共享的入库组件。"""

    repository: SqliteKnowledgeIngestionRepository
    coordinator: KnowledgeIngestionCoordinator
    hook: AutoIngestionHook
    worker: KnowledgeIngestionWorker
    vector_writer: QdrantKnowledgeIndexWriter
    deletion_service: KnowledgeDeletionService


def compose_knowledge_ingestion(
    *,
    settings: Settings,
    database: SqliteConnectionFactory,
    qdrant_client_provider: LocalQdrantClientProvider,
) -> KnowledgeIngestionComposition:
    """创建自动捕获、切块、Embedding、双索引写入和后台 Worker。"""

    repository = SqliteKnowledgeIngestionRepository(database)
    projectors = ArtifactProjectorRegistry(
        (CodeAnalysisProjector(), LearningNoteProjector())
    )
    coordinator = KnowledgeIngestionCoordinator(
        repository=repository,
        projectors=projectors,
    )
    hook = AutoIngestionHook(
        coordinator=coordinator,
        policy=AutoIngestionPolicy(),
    )
    vector_writer = QdrantKnowledgeIndexWriter(
        client_provider=qdrant_client_provider,
        collections={
            KnowledgeSpace.PROJECT_CODE: settings.rag_project_code_collection,
            KnowledgeSpace.PERSONAL_KNOWLEDGE: settings.rag_personal_knowledge_collection,
            KnowledgeSpace.USER_MEMORY: settings.rag_user_memory_collection,
        },
    )
    indexing_service = KnowledgeIndexingService(
        repository=repository,
        chunker=AssetChunkerRouter(),
        embedder=SentenceTransformerEmbedder(
            settings.rag_embedding_model,
            local_files_only=settings.rag_models_local_files_only,
            cache_folder=settings.rag_model_cache_directory,
        ),
        vector_writer=vector_writer,
    )
    worker = KnowledgeIngestionWorker(
        repository=repository,
        indexing_service=indexing_service,
        poll_seconds=settings.knowledge_ingestion_poll_seconds,
        batch_size=settings.knowledge_ingestion_batch_size,
        max_attempts=settings.knowledge_ingestion_max_attempts,
    )
    return KnowledgeIngestionComposition(
        repository=repository,
        coordinator=coordinator,
        hook=hook,
        worker=worker,
        vector_writer=vector_writer,
        deletion_service=KnowledgeDeletionService(repository),
    )

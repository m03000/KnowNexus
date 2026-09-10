"""RAG 检索领域的依赖组合模块，集中创建具体模型和存储适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.capabilities.rag import RetrievalMiniAgent
from study_help_agent.capabilities.rag.infrastructure import (
    CrossEncoderReranker,
    InMemoryRetrievalCache,
    QdrantChunkStore,
    SentenceTransformerEmbedder,
    SqliteFTS5Retriever,
)
from study_help_agent.capabilities.knowledge_ingestion.infrastructure import (
    SqliteKnowledgeIngestionRepository,
)
from study_help_agent.capabilities.rag.llm import (
    GroundedAnswerOperations,
    RetrievalLLMOperations,
)
from study_help_agent.capabilities.rag.mini_agents import GroundedAnswerMiniAgent
from study_help_agent.capabilities.rag.mini_agents.grounded_answer_agent.nodes import (
    GroundedAnswerGraphNodes,
)
from study_help_agent.capabilities.rag.mini_agents.rag_retrieval_agent.nodes import (
    RetrievalGraphNodes,
)
from study_help_agent.core.config import Settings
from study_help_agent.runtime.tools import ToolDefinition
from study_help_agent.tools.rag import create_rag_tool_groups
from study_help_agent.infrastructure.search import LocalQdrantClientProvider
from study_help_agent.infrastructure.persistence.sqlite import SqliteConnectionFactory
from study_help_agent.capabilities.knowledge_graph.retrieval import (
    CodeTreeRetriever,
    CompositeGraphRetriever,
)
from study_help_agent.capabilities.knowledge_graph.projections.memory_graph import (
    MemoryStructureRetriever,
)
from study_help_agent.capabilities.knowledge_graph.projections.project_graph import (
    ProjectStructureRetriever,
)
from study_help_agent.capabilities.llm_wiki.infrastructure import SqliteWikiRepository
from study_help_agent.capabilities.llm_wiki.retrieval import WikiRetriever

if TYPE_CHECKING:
    from study_help_agent.capabilities.long_term_memory.memory_store import MemoryStore


@dataclass(frozen=True, slots=True)
class RAGComposition:
    """向应用组合根公开检索 Mini-Agent 和工具组。"""

    mini_agent: RetrievalMiniAgent
    tool_groups: tuple[tuple[ToolDefinition, ...], ...]
    vector_store: QdrantChunkStore


def compose_rag(
    *,
    settings: Settings,
    llm: BaseChatModel,
    knowledge_repository: SqliteKnowledgeIngestionRepository,
    database: SqliteConnectionFactory,
    qdrant_client_provider: LocalQdrantClientProvider | None = None,
    code_service=None,
    memory_store: MemoryStore | None = None,
) -> RAGComposition:
    """选择装配标准化混合检索链，所有重模型均延迟加载。"""
    embedder = SentenceTransformerEmbedder(
        settings.rag_embedding_model,
        local_files_only=settings.rag_models_local_files_only,
        cache_folder=settings.rag_model_cache_directory,
    )
    vector_store = QdrantChunkStore(
        database_path=settings.rag_vector_database_path,
        collection_name=settings.rag_personal_knowledge_collection,
        embedder=embedder,
        client_provider=qdrant_client_provider,
        collections={
            "project_code": settings.rag_project_code_collection,
            "personal_knowledge": settings.rag_personal_knowledge_collection,
            "user_memory": settings.rag_user_memory_collection,
        },
    )
    graph_retriever = CompositeGraphRetriever(
        personal_retriever=WikiRetriever(SqliteWikiRepository(database)),
        project_retriever=(
            CodeTreeRetriever(
                vector_store=vector_store,
                code_service=code_service,
                fallback_retriever=ProjectStructureRetriever(
                    code_service=code_service,
                    vector_store=vector_store,
                ),
            )
            if code_service is not None
            else None
        ),
        memory_retriever=(
            MemoryStructureRetriever(
                memory_store=memory_store,
                vector_store=vector_store,
            )
            if memory_store is not None
            else None
        ),
    )
    mini_agent = RetrievalMiniAgent(
        nodes=RetrievalGraphNodes(
            lexical_retriever=SqliteFTS5Retriever(knowledge_repository),
            vector_retriever=vector_store,
            reranker=CrossEncoderReranker(
                settings.rag_reranker_model,
                local_files_only=settings.rag_models_local_files_only,
                cache_folder=settings.rag_model_cache_directory,
            ),
            graph_retriever=graph_retriever,
            llm_operations=RetrievalLLMOperations(llm),
        ),
        cache=InMemoryRetrievalCache(settings.rag_retrieval_cache_ttl_seconds),
        index_revision_provider=knowledge_repository.index_revision,
    )
    return RAGComposition(
        mini_agent=mini_agent,
        tool_groups=create_rag_tool_groups(
            mini_agent=mini_agent,
            answer_mini_agent=GroundedAnswerMiniAgent(
                nodes=GroundedAnswerGraphNodes(
                    operations=GroundedAnswerOperations(llm)
                )
            ),
        ),
        vector_store=vector_store,
    )

"""应用运行期间共享依赖的数据容器。

本模块只声明容器字段，不创建任何具体依赖。依赖创建和连接由 ``bootstrap`` 及
``app.composition`` 负责，API 层通过该容器取得已经组装完成的服务。
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.core.config import Settings
from study_help_agent.infrastructure.persistence.sqlite import (
    SqliteConnectionFactory,
)
from study_help_agent.capabilities.code_analysis.application.service import (
    CodeAnalysisService,
)
from study_help_agent.capabilities.learning_notes.application.service import (
    LearningNoteService,
)
from study_help_agent.capabilities.knowledge_graph.application.graph_service import (
    GraphQueryService,
)
from study_help_agent.runtime import (
    AgentRunRegistry,
    InMemoryArtifactStore,
    SkillRegistry,
    ToolRegistry,
)
from study_help_agent.capabilities.rag import RetrievalMiniAgent
from study_help_agent.agents import (
    AgentLoopFactory,
    AgentProfileRegistry,
    MainAgentService,
)
from study_help_agent.capabilities.knowledge_ingestion.application.coordinator import (
    KnowledgeIngestionCoordinator,
)
from study_help_agent.capabilities.knowledge_ingestion.application.deletion_service import (
    KnowledgeDeletionService,
)
from study_help_agent.capabilities.knowledge_ingestion.infrastructure import (
    KnowledgeIngestionWorker,
    SqliteKnowledgeIngestionRepository,
)
from study_help_agent.infrastructure.search import LocalQdrantClientProvider
from study_help_agent.capabilities.external_conversation import (
    ExternalConversationCaptureService,
)
from study_help_agent.infrastructure.models import ModelManager
from study_help_agent.capabilities.llm_wiki.infrastructure.worker import WikiBuildWorker

@dataclass(slots=True)
class AppContainer:
    """保存整个运行中应用共享的服务、Runtime 和 Agent 对象。"""

    settings: Settings
    llm: BaseChatModel
    database: SqliteConnectionFactory

    code_analysis_service: CodeAnalysisService
    learning_note_service: LearningNoteService
    rag_retrieval_mini_agent: RetrievalMiniAgent
    loop_artifact_store: InMemoryArtifactStore
    loop_tool_registry: ToolRegistry
    loop_skill_registry: SkillRegistry
    agent_profiles: AgentProfileRegistry
    agent_loop_factory: AgentLoopFactory
    main_agent_service: MainAgentService
    agent_run_registry: AgentRunRegistry
    knowledge_ingestion_repository: SqliteKnowledgeIngestionRepository
    knowledge_ingestion_coordinator: KnowledgeIngestionCoordinator
    knowledge_deletion_service: KnowledgeDeletionService
    knowledge_ingestion_worker: KnowledgeIngestionWorker
    wiki_build_worker: WikiBuildWorker
    qdrant_client_provider: LocalQdrantClientProvider
    graph_query_service: GraphQueryService
    external_conversation_capture_service: ExternalConversationCaptureService
    model_manager: ModelManager

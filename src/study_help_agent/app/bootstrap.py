"""应用总组合根。

本文件只创建共享基础设施、调用各领域 composition、注册工具与 Skill，并组装 Agent。
具体业务仓储、Runner、Worker 和 Provider 的连接细节位于 ``app.composition``。
"""

from __future__ import annotations

from pathlib import Path

from study_help_agent.agents import (
    AgentLoopFactory,
    MainAgentService,
    ResponseComposer,
    SubAgentDelegationTools,
    create_default_profiles,
)
from study_help_agent.agents.routing import MainIntentRouter
from study_help_agent.app.composition import (
    compose_code_analysis,
    compose_note,
    compose_long_term_memory,
    compose_rag,
    compose_knowledge_ingestion,
    compose_runtime_tool_groups,
    compose_conversation_context,
    compose_external_conversation,
)
from study_help_agent.app.composition import compose_knowledge_graph
from study_help_agent.app.container import AppContainer
from study_help_agent.core.config import Settings, get_settings
from study_help_agent.infrastructure.filesystem.safe_path import SafeProjectPathResolver
from study_help_agent.infrastructure.llm.factory import create_chat_model
from study_help_agent.infrastructure.persistence import SqliteConnectionFactory
from study_help_agent.infrastructure.search import LocalQdrantClientProvider
from study_help_agent.runtime import (
    AgentRunRegistry,
    FileSystemSkillLoader,
    InMemoryArtifactStore,
    LoopToolSet,
    SkillRegistry,
    ToolRegistry,
    MainWebResearchTools,
)
from study_help_agent.infrastructure.models import ModelManager


def build_container(settings: Settings | None = None) -> AppContainer:
    """创建整个进程唯一的应用依赖容器。"""

    # 加载基础配置
    actual_settings = settings or get_settings()
    llm = create_chat_model(actual_settings)
    database = SqliteConnectionFactory(
        database_path=actual_settings.database_path,
        timeout_seconds=actual_settings.sqlite_timeout_seconds,
        busy_timeout_ms=actual_settings.sqlite_busy_timeout_ms,
    )
    path_resolver = SafeProjectPathResolver(
        allowed_roots=actual_settings.allowed_project_roots
    )
    qdrant_client_provider = LocalQdrantClientProvider(
        actual_settings.rag_vector_database_path
    )

    # 各个领域的实现
    code_analysis = compose_code_analysis(
        settings=actual_settings,
        llm=llm,
        database=database,
        path_resolver=path_resolver,
    )
    knowledge_ingestion = compose_knowledge_ingestion(
        settings=actual_settings,
        database=database,
        qdrant_client_provider=qdrant_client_provider,
    )
    note = compose_note(
        settings=actual_settings,
        llm=llm,
        database=database,
        knowledge_repository=knowledge_ingestion.repository,
        knowledge_deletion=knowledge_ingestion.deletion_service,
    )
    conversation_context = compose_conversation_context(llm=llm, database=database)
    long_term_memory = compose_long_term_memory(
        llm=llm,
        database=database,
        knowledge_repository=knowledge_ingestion.repository,
        consolidation_repository=conversation_context.repository,
    )
    conversation_context.service.set_turn_indexer(long_term_memory.search_indexer)
    rag = compose_rag(
        settings=actual_settings,
        llm=llm,
        knowledge_repository=knowledge_ingestion.repository,
        database=database,
        qdrant_client_provider=qdrant_client_provider,
        code_service=code_analysis.analysis_service,
        memory_store=long_term_memory.store,
    )

    artifact_store = InMemoryArtifactStore()

    tool_registry = ToolRegistry()
    LoopToolSet(
        (
            *compose_runtime_tool_groups(actual_settings),
            *code_analysis.tool_groups,
            *note.tool_groups,
            *rag.tool_groups,
        )
    ).register_into(tool_registry)
    # 这些定义进入全局注册表，但只有 Main Profile 列出名称，因此子 Agent 无权调用。
    tool_registry.register_many(MainWebResearchTools().definitions())

    skill_registry = SkillRegistry()
    skill_registry.register_many(
        FileSystemSkillLoader(
            root=Path(__file__).resolve().parents[1] / "skills"
        ).load_all()
    )

    profiles = create_default_profiles()
    agent_loop_factory = AgentLoopFactory(
        llm=llm,
        tools=tool_registry,
        skills=skill_registry,
        artifacts=artifact_store,
        profiles=profiles,
        result_observers=(knowledge_ingestion.hook,),
    )

    # 注册主 Agent使用的三个sub agent
    tool_registry.register_many(
        SubAgentDelegationTools(factory=agent_loop_factory).definitions()
    )
    main_agent_service = MainAgentService(
        factory=agent_loop_factory,
        profiles=profiles,
        intent_router=MainIntentRouter(),
        conversation_context=conversation_context.service,
        memory_consolidator=long_term_memory.consolidation,
        response_composer=ResponseComposer(llm=llm),
    )
    agent_run_registry = AgentRunRegistry()
    graph_query_service = compose_knowledge_graph(
        note_service=note.note_service,
        code_service=code_analysis.analysis_service,
        memory_store=long_term_memory.store,
        conversation_repository=conversation_context.repository,
        database=database,
        vector_store=rag.vector_store,
    )
    external_conversation_capture_service = compose_external_conversation(
        repository=conversation_context.repository,
        memory_consolidator=long_term_memory.consolidation,
        turn_indexer=long_term_memory.search_indexer,
    )
    return AppContainer(
        settings=actual_settings,
        llm=llm,
        database=database,
        code_analysis_service=code_analysis.analysis_service,
        learning_note_service=note.note_service,
        rag_retrieval_mini_agent=rag.mini_agent,
        loop_artifact_store=artifact_store,
        loop_tool_registry=tool_registry,
        loop_skill_registry=skill_registry,
        agent_profiles=profiles,
        agent_loop_factory=agent_loop_factory,
        main_agent_service=main_agent_service,
        agent_run_registry=agent_run_registry,
        knowledge_ingestion_repository=knowledge_ingestion.repository,
        knowledge_ingestion_coordinator=knowledge_ingestion.coordinator,
        knowledge_deletion_service=knowledge_ingestion.deletion_service,
        knowledge_ingestion_worker=knowledge_ingestion.worker,
        wiki_build_worker=note.wiki_build_worker,
        qdrant_client_provider=qdrant_client_provider,
        graph_query_service=graph_query_service,
        external_conversation_capture_service=external_conversation_capture_service,
        model_manager=ModelManager(actual_settings, llm=llm),
    )

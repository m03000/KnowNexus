"""FastAPI 依赖读取函数。"""

from typing import cast
from fastapi import Request

from study_help_agent.app.container import AppContainer
from study_help_agent.core.config import Settings
from study_help_agent.agents import MainAgentService
from study_help_agent.runtime import AgentRunRegistry
from study_help_agent.capabilities.code_analysis.application.service import (
    CodeAnalysisService,
)
from study_help_agent.capabilities.knowledge_graph.application.graph_service import (
    GraphQueryService,
)
from study_help_agent.capabilities.learning_notes.application.service import LearningNoteService
from study_help_agent.capabilities.knowledge_ingestion.application.deletion_service import (
    KnowledgeDeletionService,
)
from study_help_agent.capabilities.external_conversation import (
    ExternalConversationCaptureService,
)
from study_help_agent.infrastructure.models import ModelManager
from study_help_agent.capabilities.llm_wiki.infrastructure import SqliteWikiRepository


def get_container(request: Request) -> AppContainer:
    """获取当前 FastAPI 应用的依赖容器。"""

    # 等价于 request.app.state.container，使用 getattr 加默认值 None，防止属性不存在时抛 AttributeError。
    container = getattr(
        request.app.state,
        "container",
        None,
    )

    if container is None:
        raise RuntimeError(
            "AppContainer 尚未初始化，"
            "请确认应用通过 lifespan 正常启动"
        )

    return cast(AppContainer, container)


def get_app_settings(request: Request,) -> Settings:
    """获取当前应用配置。"""

    return get_container(request).settings


def get_main_agent_service(request: Request) -> MainAgentService:
    """获取新的主 Agent Loop 应用服务。"""

    return get_container(request).main_agent_service


def get_agent_run_registry(request: Request) -> AgentRunRegistry:
    """返回进程内 Agent任务生命周期注册表。"""

    return get_container(request).agent_run_registry


def get_code_analysis_service(request: Request) -> CodeAnalysisService:
    """返回前端代码解析查询与删除服务。"""

    return get_container(request).code_analysis_service


def get_learning_note_service(request: Request) -> LearningNoteService:
    """返回前端笔记查询与删除服务。"""

    return get_container(request).learning_note_service


def get_knowledge_deletion_service(request: Request) -> KnowledgeDeletionService:
    """返回负责异步清理 FTS5/Qdrant 的知识删除协调器。"""

    return get_container(request).knowledge_deletion_service


def get_graph_query_service(request: Request) -> GraphQueryService:
    """返回统一图谱查询服务。"""
    return get_container(request).graph_query_service


def get_external_conversation_capture_service(
    request: Request,
) -> ExternalConversationCaptureService:
    """返回供 HTTP Hook 与 MCP 共同复用的外部对话捕获服务。"""

    return get_container(request).external_conversation_capture_service


def get_model_manager(request: Request) -> ModelManager:
    """返回桌面端模型配置与下载服务。"""
    return get_container(request).model_manager


def get_wiki_repository(request: Request) -> SqliteWikiRepository:
    return SqliteWikiRepository(get_container(request).database)

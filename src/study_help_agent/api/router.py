"""Agent-first 应用路由汇总。"""

from fastapi import APIRouter

from study_help_agent.agents import router as agent_router
from study_help_agent.api.code_library import router as code_library_router
from study_help_agent.api.note_library import router as note_library_router
from study_help_agent.api.graph_library import router as graph_library_router
from study_help_agent.api.external_conversations import router as external_conversations_router
from study_help_agent.api.external_watchers import router as external_watchers_router
from study_help_agent.api.conversation_history import router as conversation_history_router
from study_help_agent.api.model_management import router as model_management_router
from study_help_agent.api.wiki_library import router as wiki_library_router
from study_help_agent.api.obsidian_wiki import router as obsidian_wiki_router
from study_help_agent.api.memory_maintenance import router as memory_maintenance_router


def create_api_router() -> APIRouter:
    """创建并汇总整个应用的 API Router。"""

    router = APIRouter()

    router.include_router(agent_router)
    router.include_router(code_library_router)
    router.include_router(note_library_router)
    router.include_router(graph_library_router)
    router.include_router(external_conversations_router)
    router.include_router(external_watchers_router)
    router.include_router(conversation_history_router)
    router.include_router(model_management_router)
    router.include_router(wiki_library_router)
    router.include_router(obsidian_wiki_router)
    router.include_router(memory_maintenance_router)

    return router

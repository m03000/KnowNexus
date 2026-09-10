from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextlib import AsyncExitStack
import asyncio

from fastapi import FastAPI

from study_help_agent.app.bootstrap import build_container
from study_help_agent.core.config import Settings
from study_help_agent.infrastructure.persistence import initialize_database
from study_help_agent.integrations.watcher_registry import ExternalWatcherRegistry
from study_help_agent.api.memory_maintenance import DailyMemorySummaryService, run_daily_summary_loop


def create_lifespan(settings: Settings, *, mcp_session_manager=None):
    """Create the FastAPI startup and shutdown lifecycle."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings)

        app.state.container = container

        external_watcher_registry = ExternalWatcherRegistry(
            settings=settings,
            capture_service=container.external_conversation_capture_service,
            database=container.database,
        )
        app.state.external_watcher_registry = external_watcher_registry
        daily_summary_service = DailyMemorySummaryService(container.database, container.llm, container.learning_note_service)
        app.state.daily_memory_summary_service = daily_summary_service

        initialize_database(container.database)
        # v18 起 USER_MEMORY 搜索索引只保存原始对话；清理旧版 memory:<id> 投影。
        container.knowledge_ingestion_repository.request_delete_by_source_prefix(
            "memory:"
        )

        async with AsyncExitStack() as stack:
            # 被 Mount 的 ASGI 子应用不会自动运行自己的 lifespan，必须由宿主托管。
            if mcp_session_manager is not None:
                await stack.enter_async_context(mcp_session_manager.run())

            if settings.knowledge_ingestion_enabled:
                await container.knowledge_ingestion_worker.start()
            await container.wiki_build_worker.start()

            # 每个外部监听器有自己的 enabled 状态；不能再由 Codex 全局开关
            # 一并阻止 WorkBuddy 等已配置监听器在重启后恢复。
            external_watcher_registry.start_enabled()
            daily_summary_task = asyncio.create_task(run_daily_summary_loop(daily_summary_service))

            try:
                yield
            finally:
                daily_summary_task.cancel()
                await asyncio.to_thread(
                    external_watcher_registry.stop,
                    timeout=settings.agent_shutdown_grace_seconds,
                )
                container.agent_run_registry.cancel_all("应用正在关闭")
                await asyncio.to_thread(
                    container.agent_run_registry.wait_for_idle,
                    settings.agent_shutdown_grace_seconds,
                )
                if settings.knowledge_ingestion_enabled:
                    await container.knowledge_ingestion_worker.stop()
                await container.wiki_build_worker.stop()
                container.qdrant_client_provider.close()

    return lifespan

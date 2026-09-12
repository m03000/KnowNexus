from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from study_help_agent.api.exception_handlers import (
    register_exception_handlers,
)
from study_help_agent.api.router import create_api_router
from study_help_agent.app.lifespan import create_lifespan
from study_help_agent.core.config import (
    Settings,
    get_settings,
)
from study_help_agent.interfaces.mcp import create_mcp_server


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    actual_settings = settings or get_settings()

    app_holder: dict[str, FastAPI] = {}
    mcp_server = create_mcp_server(
        lambda: app_holder["app"].state.container
    )
    mcp_app = mcp_server.streamable_http_app()

    app = FastAPI(
        title=actual_settings.app_name,
        version="0.1.0",
        debug=actual_settings.debug,
        lifespan=create_lifespan(
            actual_settings,
            mcp_session_manager=mcp_server.session_manager,
        ),
    )
    app_holder["app"] = app

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=actual_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(
        create_api_router()
    )

    register_system_routes(app)

    # streamable_http_path="/"，所以客户端连接地址正好是 /mcp。
    app.mount("/mcp", mcp_app, name="personal-agent-mcp")

    return app


def register_system_routes(
    app: FastAPI,
) -> None:
    @app.get("/", tags=["system"])
    async def application_info() -> dict[str, str]:
        return {
            "name": app.title,
            "status": "running",
        }

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {
            "status": "ok",
            "app": "KnowNexus",
            "version": app.version,
        }


app = create_app()

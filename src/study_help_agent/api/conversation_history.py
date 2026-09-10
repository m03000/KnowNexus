"""外部智能体历史会话查询、预览和选择性导入接口。"""
from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field

from study_help_agent.integrations.conversation_history import ExternalHistoryService

router = APIRouter(prefix="/api/integrations/conversation-history", tags=["conversation-history"])


class SessionRequest(BaseModel):
    client: str = Field(pattern="^(codex|workbuddy)$")
    session_id: str = Field(min_length=1, max_length=300)


def _service(request: Request) -> ExternalHistoryService:
    container = request.app.state.container
    return ExternalHistoryService(
        codex_root=container.settings.codex_watcher_sessions_directory,
        capture_service=container.external_conversation_capture_service,
    )


@router.get("/sessions")
def list_history_sessions(request: Request,
    client: str = Query(default="codex", pattern="^(codex|workbuddy)$"),
    limit: int = Query(default=30, ge=1, le=100)) -> dict:
    try:
        return {"client": client, "sessions": _service(request).list_sessions(client=client, limit=limit)}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preview")
def preview_history_session(payload: SessionRequest, request: Request,
                            limit: int = Query(default=20, ge=1, le=100)) -> dict:
    try:
        return _service(request).preview(
            client=payload.client, session_id=payload.session_id, limit=limit
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/import")
def import_history_session(payload: SessionRequest, request: Request,
    background_tasks: BackgroundTasks) -> dict:
    try:
        service = _service(request)
        result = service.import_session(client=payload.client, session_id=payload.session_id)
        background_tasks.add_task(service.consolidate, result["session_id"])
        return result
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

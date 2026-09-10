"""多外部智能体监听服务的状态与管理接口。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

# 路径暂时保留，避免破坏已发布前端；内部已经是多智能体统一监听服务。
router = APIRouter(prefix="/api/integrations/codex-watcher", tags=["external-watchers"])


class WatcherConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parser_type: str = Field(default="generic", max_length=80)
    adapter_id: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    session_index_path: str = Field(default="", max_length=4000)
    conversation_root: str = Field(default="", max_length=4000)
    memory_path: str = Field(default="", max_length=4000)

    def values(self) -> dict[str, Any]:
        return self.model_dump()


def _manager(request: Request):
    manager = getattr(request.app.state, "external_watcher_registry", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="外部智能体监听服务尚未初始化")
    return manager


@router.get("")
def get_external_watcher_status(request: Request) -> dict:
    """返回监听器当前状态。"""

    return _manager(request).status()


@router.get("/statistics")
def get_watcher_statistics(request: Request, start_at: str = "", end_at: str = "") -> dict:
    """读取关系型数据库中的监听历史，可按 ISO 时间范围筛选。"""

    return _manager(request).statistics(start_at=start_at, end_at=end_at)


@router.get("/adapters")
def list_adapters(request: Request) -> dict:
    return _manager(request).adapters()


class AdapterGenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sample_path: str = Field(min_length=1, max_length=4000)


class AdapterTestRequest(BaseModel):
    adapter_id: str = Field(min_length=1, max_length=80)
    session_index_path: str = Field(default="", max_length=4000)
    conversation_root: str = Field(default="", max_length=4000)
    memory_path: str = Field(default="", max_length=4000)


@router.post("/adapters/generate")
def generate_adapter(payload: AdapterGenerateRequest, request: Request) -> dict:
    try:
        return _manager(request).generate_adapter(payload.model_dump())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/adapters/test")
def test_adapter(payload: AdapterTestRequest, request: Request) -> dict:
    try:
        return _manager(request).test_adapter(payload.model_dump())
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start")
def start_external_watchers(request: Request) -> dict:
    """幂等启动监听器。"""

    return _manager(request).start()


@router.post("/stop")
def stop_external_watchers(request: Request) -> dict:
    """安全停止监听器；已完成捕获仍会在退出前投递。"""

    return _manager(request).stop()


@router.post("/watchers")
def add_watcher(payload: WatcherConfigRequest, request: Request) -> dict:
    try:
        return _manager(request).add(payload.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/watchers/{watcher_id}")
def update_watcher(watcher_id: str, payload: WatcherConfigRequest,
                   request: Request) -> dict:
    try:
        return _manager(request).update(watcher_id, payload.values())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/watchers/{watcher_id}")
def delete_watcher(watcher_id: str, request: Request) -> dict:
    try:
        return _manager(request).delete(watcher_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/watchers/{watcher_id}/start")
def start_watcher(watcher_id: str, request: Request) -> dict:
    try:
        return _manager(request).start(watcher_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/watchers/{watcher_id}/stop")
def stop_watcher(watcher_id: str, request: Request) -> dict:
    try:
        return _manager(request).stop(watcher_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

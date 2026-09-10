"""主 Agent Loop 的 HTTP API。"""

from typing import Annotated
import asyncio
from dataclasses import asdict
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from study_help_agent.agents import MainAgentService
from study_help_agent.api.dependencies import (
    get_agent_run_registry,
    get_main_agent_service,
)
from study_help_agent.runtime import AgentRunRegistry, StreamEvent
from study_help_agent.observability import get_observability_recorder, trace_scope


class AgentChatRequest(BaseModel):
    """主 Agent 对话请求。"""

    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str | None = Field(
        default=None,
        description="前端生成的请求幂等键；重试同一轮时必须复用",
    )


class CreateAgentSessionRequest(BaseModel):
    """创建空白网页会话；消息和 Agent Run 在后续独立产生。"""

    session_id: str | None = None
    title: str = Field(default="新对话", max_length=100)


router = APIRouter(prefix="/api/agent", tags=["Loop 多 Agent"])
Service = Annotated[MainAgentService, Depends(get_main_agent_service)]
Runs = Annotated[AgentRunRegistry, Depends(get_agent_run_registry)]
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(request: AgentChatRequest, service: Service, runs: Runs):
    """在线程中执行同步 Agent Loop，避免阻塞 ASGI 事件循环。"""

    logger.info(
        "收到 Agent 对话请求 session_id=%s turn_id=%s",
        request.session_id,
        request.turn_id,
    )
    public_run_id = request.turn_id or f"turn-{uuid4().hex}"
    recorder = get_observability_recorder()
    recorder.start_run(
        run_id=public_run_id, trace_id=public_run_id,
        session_id=request.session_id, turn_id=public_run_id,
        request_text=request.message,
    )
    try:
        run = runs.create(
            run_id=public_run_id,
            session_id=request.session_id,
            turn_id=public_run_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    runs.mark_running(public_run_id)
    try:
        def execute_traced():
            with trace_scope(
                run_id=public_run_id, trace_id=public_run_id,
                session_id=request.session_id, turn_id=public_run_id, agent="main",
            ):
                return service.run(
                    message=request.message, session_id=request.session_id,
                    turn_id=public_run_id, cancellation_token=run.token,
                )

        response = await asyncio.to_thread(execute_traced)
        runs.finish(public_run_id, status=response.status)
        recorder.finish_run(
            run_id=public_run_id, status=response.status,
            iterations=response.iterations, tool_calls=response.tool_calls,
            artifact_ids=response.artifact_ids,
        )
        return response
    except Exception as error:
        runs.finish(public_run_id, status="failed", error=str(error))
        recorder.finish_run(run_id=public_run_id, status="failed", error=str(error))
        raise


@router.post("/chat/stream")
async def stream_chat(request: AgentChatRequest, service: Service, runs: Runs):
    """以 SSE 输出真实路由、Agent、工具阶段以及最终回答片段。"""

    queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    public_run_id = request.turn_id or f"turn-{uuid4().hex}"
    recorder = get_observability_recorder()
    recorder.start_run(
        run_id=public_run_id, trace_id=public_run_id,
        session_id=request.session_id, turn_id=public_run_id,
        request_text=request.message,
    )
    try:
        run = runs.create(
            run_id=public_run_id,
            session_id=request.session_id,
            turn_id=public_run_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    terminal_published = False

    def publish(event: StreamEvent) -> None:
        nonlocal terminal_published
        if event.event in {"done", "error"}:
            terminal_published = True
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def execute() -> None:
        runs.mark_running(public_run_id)
        try:
            def execute_traced():
                with trace_scope(
                    run_id=public_run_id, trace_id=public_run_id,
                    session_id=request.session_id, turn_id=public_run_id, agent="main",
                ):
                    return service.run(
                        message=request.message, session_id=request.session_id,
                        turn_id=public_run_id, event_sink=publish,
                        cancellation_token=run.token,
                    )

            response = await asyncio.to_thread(execute_traced)
            runs.finish(public_run_id, status=response.status)
            recorder.finish_run(
                run_id=public_run_id, status=response.status,
                iterations=response.iterations, tool_calls=response.tool_calls,
                artifact_ids=response.artifact_ids,
            )
            # 协议兜底：即便未来新增提前返回路径，SSE 也必须显式终止。
            if not terminal_published:
                publish(StreamEvent(
                    event="done",
                    run_id=public_run_id,
                    data={"response": asdict(response)},
                    agent="main",
                ))
        except Exception as error:
            runs.finish(public_run_id, status="failed", error=str(error))
            recorder.finish_run(run_id=public_run_id, status="failed", error=str(error))
            publish(StreamEvent(
                event="error",
                run_id=public_run_id,
                data={"message": str(error)},
                agent="main",
            ))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def event_stream():
        created = StreamEvent(
            event="run_created",
            run_id=public_run_id,
            data={"run_id": public_run_id, "status": "queued"},
            agent="main",
        )
        payload = json.dumps(created.as_dict(), ensure_ascii=False, default=str)
        yield f"event: run_created\ndata: {payload}\n\n"
        task = asyncio.create_task(execute())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                payload = json.dumps(event.as_dict(), ensure_ascii=False, default=str)
                yield f"event: {event.event}\ndata: {payload}\n\n"
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}")
def get_run(run_id: str, runs: Runs):
    """查询当前进程中的 Agent任务状态。"""

    try:
        return runs.get(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, runs: Runs):
    """幂等请求取消一个 Agent任务；正在执行的同步LLM会在返回后观察取消。"""

    try:
        return runs.cancel(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/profiles")
def list_profiles(service: Service):
    """列出主 Agent 和专业 Sub-Agent 的能力边界。"""

    return {"profiles": service.profiles()}


@router.get("/sessions")
def list_sessions(service: Service):
    """列出对话主页中的内部会话。"""

    return {"sessions": service.list_sessions()}


@router.post("/sessions")
def create_session(request: CreateAgentSessionRequest, service: Service):
    """立即持久化一个空会话并返回稳定 ID。"""

    session_id = (request.session_id or "").strip() or f"session-{uuid4().hex}"
    try:
        return service.create_session(session_id, title=request.title)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/sessions/{session_id}/messages")
def get_session_messages(session_id: str, service: Service):
    """读取一个内部会话的消息历史。"""

    return {"session_id": session_id, "messages": service.get_session_messages(session_id)}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, service: Service):
    """删除短期会话，但不删除已经蒸馏的长期记忆。"""

    if not service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True, "session_id": session_id}

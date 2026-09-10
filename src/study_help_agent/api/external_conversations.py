"""外部智能体对话捕获 HTTP 接口。

该接口是 Codex Hook 的可靠本地写入端，也可供不支持 MCP 写操作的平台适配器使用。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from study_help_agent.api.dependencies import get_external_conversation_capture_service
from study_help_agent.capabilities.external_conversation import (
    ExternalConversationCaptureService,
    ExternalConversationTurn,
)

router = APIRouter(prefix="/api/external-conversations", tags=["external-conversations"])
CaptureService = Annotated[
    ExternalConversationCaptureService,
    Depends(get_external_conversation_capture_service),
]


class ExternalTurnRequest(BaseModel):
    """跨客户端稳定的完整轮次传输对象。"""

    client: str = Field(min_length=1, max_length=50)
    external_session_id: str = Field(min_length=1, max_length=300)
    external_turn_id: str = Field(min_length=1, max_length=300)
    user_message: str = Field(min_length=1)
    assistant_message: str = Field(min_length=1)
    title: str = Field(default="", max_length=500)
    cwd: str = Field(default="", max_length=2000)
    model: str = Field(default="", max_length=200)
    transcript_path: str = Field(default="", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    force_consolidation: bool = False

    def to_domain(self) -> ExternalConversationTurn:
        return ExternalConversationTurn(
            client=self.client,
            external_session_id=self.external_session_id,
            external_turn_id=self.external_turn_id,
            user_message=self.user_message,
            assistant_message=self.assistant_message,
            title=self.title,
            cwd=self.cwd,
            model=self.model,
            transcript_path=self.transcript_path,
            metadata=self.metadata,
        )


class ExternalTurnBatchRequest(BaseModel):
    """历史导入或 Hook 补偿上传使用的批量请求。"""

    turns: list[ExternalTurnRequest] = Field(min_length=1, max_length=100)
    force_last_consolidation: bool = False


class ExternalSessionFlushRequest(BaseModel):
    client: str = Field(min_length=1, max_length=50)
    external_session_id: str = Field(min_length=1, max_length=300)


@router.post("/turns")
def capture_turn(
    payload: ExternalTurnRequest,
    service: CaptureService,
    background_tasks: BackgroundTasks,
) -> dict:
    """保存一个已完成轮次；同一个外部轮次重复提交不会重复落库。"""

    result = service.capture_turn(
        payload.to_domain(),
        force_consolidation=payload.force_consolidation,
        defer_consolidation=True,
    )
    background_tasks.add_task(
        service.consolidate_session_id,
        session_id=result.session_id,
        force=payload.force_consolidation,
    )
    return _result_dict(result)


@router.post("/turns/batch")
def capture_turns(
    payload: ExternalTurnBatchRequest,
    service: CaptureService,
    background_tasks: BackgroundTasks,
) -> dict:
    """批量补录完整轮次，并可在批末强制一次长期记忆蒸馏。"""

    results = tuple(
        service.capture_turn(item.to_domain(), defer_consolidation=True)
        for item in payload.turns
    )
    sessions = list(dict.fromkeys(item.session_id for item in results))
    for index, session_id in enumerate(sessions):
        background_tasks.add_task(
            service.consolidate_session_id,
            session_id=session_id,
            force=(payload.force_last_consolidation and index == len(sessions) - 1),
        )
    return {"items": [_result_dict(item) for item in results]}


@router.post("/sessions/flush")
def flush_session(
    payload: ExternalSessionFlushRequest,
    service: CaptureService,
    background_tasks: BackgroundTasks,
) -> dict:
    """强制蒸馏某个外部会话尚未处理的原始消息。"""

    background_tasks.add_task(
        service.flush_session,
        client=payload.client,
        external_session_id=payload.external_session_id,
    )
    return {"queued": True}


def _result_dict(result) -> dict:
    return {
        "session_id": result.session_id,
        "turn_id": result.turn_id,
        "duplicate": result.duplicate,
        "user_message_id": result.user_message_id,
        "assistant_message_id": result.assistant_message_id,
        "consolidation": result.consolidation,
    }

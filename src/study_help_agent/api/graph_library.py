"""前端三域图谱统一查询接口。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from study_help_agent.api.dependencies import get_graph_query_service
from study_help_agent.capabilities.knowledge_graph.application import (
    GraphQueryService,
    MemoryGraphQuery,
)


router = APIRouter(prefix="/api/graphs", tags=["三域图谱"])
GraphService = Annotated[GraphQueryService, Depends(get_graph_query_service)]


class RenameMemorySessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.get("")
def get_graphs(
    service: GraphService,
    query: Annotated[str | None, Query(max_length=200)] = None,
    memory_type: Annotated[str | None, Query(max_length=30)] = None,
    topic: Annotated[str | None, Query(max_length=50)] = None,
    min_importance: Annotated[int | None, Query(ge=1, le=5)] = None,
    limit: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """兼容旧客户端的聚合端点；新客户端应调用各领域独立端点。"""
    return service.get_all_graphs(
        memory_query=MemoryGraphQuery(
            query=query,
            memory_type=memory_type,
            topic=topic,
            min_importance=min_importance,
            limit=limit,
        )
    )


@router.get("/notes")
def get_note_graph(service: GraphService) -> dict:
    """只加载笔记与知识点图谱。"""

    return service.get_note_graph()


@router.get("/memory")
def get_memory_graph(
    service: GraphService,
    query: Annotated[str | None, Query(max_length=200)] = None,
    memory_type: Annotated[str | None, Query(max_length=30)] = None,
    topic: Annotated[str | None, Query(max_length=50)] = None,
    min_importance: Annotated[int | None, Query(ge=1, le=5)] = None,
    limit: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """只加载记忆图谱，支持语义查询与元数据过滤。"""

    return service.get_memory_graph(MemoryGraphQuery(
        query=query, memory_type=memory_type, topic=topic,
        min_importance=min_importance, limit=limit,
    ))


@router.patch("/memory/sessions/{session_id}")
def rename_memory_session(
    session_id: str, payload: RenameMemorySessionRequest, service: GraphService,
) -> dict:
    """修改记忆目录中的本地会话显示名称。"""

    try:
        renamed = service.rename_memory_session(session_id, payload.title)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not renamed:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "title": payload.title.strip(), "renamed": True}


@router.delete("/memory/sessions/{session_id}")
def delete_memory_session(session_id: str, service: GraphService) -> dict:
    """删除会话、本地消息，以及该会话产生的记忆点与关系。"""

    result = service.delete_memory_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session_id": session_id, "deleted": True, **result}


@router.get("/projects")
def get_project_graph(
    service: GraphService,
    project_id: Annotated[int | None, Query(ge=1)] = None,
    include_blocks: bool = True,
) -> dict:
    """加载项目图谱；默认展示项目、目录、文件以及类/函数/方法。"""

    return service.get_project_graph(
        project_id=project_id, include_blocks=include_blocks,
    )


@router.get("/projects/{project_id}/children")
def get_project_graph_children(
    project_id: int,
    service: GraphService,
    node_id: Annotated[str, Query(min_length=1, max_length=500)],
) -> dict:
    """返回项目图一个节点的直接子节点。"""

    return service.get_project_children(project_id=project_id, node_id=node_id)


@router.get("/memory/{memory_id}/trace")
def trace_memory(memory_id: str, service: GraphService) -> dict:
    """记忆溯源：记忆点 → 来源消息原话 → 来源会话聚类时间线。"""

    return service.trace_memory(memory_id)


@router.get("/memory/{memory_id}/related-candidates")
def get_memory_related_candidates(
    memory_id: str,
    service: GraphService,
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> dict:
    """返回没有显式关系、但语义上最接近的候选记忆。"""

    return {"items": service.get_memory_candidates(memory_id, limit)}


@router.get("/memory/turns/{turn_id}")
def get_memory_turn(turn_id: str, service: GraphService) -> dict:
    """读取记忆星点代表的完整原始提问和回答。"""

    return service.get_memory_turn(turn_id)


@router.delete("/memory/turns/{turn_id}")
def delete_memory_turn(turn_id: str, service: GraphService) -> dict:
    """删除单轮对话及由该轮产生的记忆点和关系。"""

    result = service.delete_memory_turn(turn_id)
    if result is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"turn_id": turn_id, "deleted": True, **result}

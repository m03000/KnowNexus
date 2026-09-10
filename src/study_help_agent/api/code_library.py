"""前端代码项目解析展示的普通 HTTP 查询与删除接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from study_help_agent.api.dependencies import (
    get_code_analysis_service,
    get_knowledge_deletion_service,
)
from study_help_agent.capabilities.code_analysis.application.service import CodeAnalysisService
from study_help_agent.capabilities.knowledge_ingestion.application.deletion_service import KnowledgeDeletionService


router = APIRouter(prefix="/api/library/code-projects", tags=["代码解析展示"])
CodeService = Annotated[CodeAnalysisService, Depends(get_code_analysis_service)]
DeletionService = Annotated[KnowledgeDeletionService, Depends(get_knowledge_deletion_service)]


@router.get("")
def list_code_projects(service: CodeService):
    """供前端读取全部已发布项目解析摘要。"""

    return {"projects": service.list_projects()}


@router.get("/{project_id}")
def get_code_project(project_id: int, service: CodeService):
    """读取一个项目解析的展示摘要。"""

    return service.get_project(project_id)


@router.get("/{project_id}/tree")
def get_code_project_tree(project_id: int, service: CodeService):
    """读取项目文件夹、文件和符号树。"""

    return {"folders": service.get_project_tree(project_id)}


@router.get("/{project_id}/file")
def get_explained_file(
    project_id: int,
    service: CodeService,
    file_path: Annotated[str, Query(min_length=1)],
):
    """读取文件源码快照、职责和代码块解释。"""

    return service.get_file_content(project_id=project_id, file_path=file_path)


@router.delete("/{project_id}")
def delete_code_project(
    project_id: int,
    service: CodeService,
    deletion: DeletionService,
):
    """删除前端展示记录，并可靠排队清理该项目的 RAG 索引。"""

    project = service.get_project(project_id)
    result = service.delete_project(project_id)
    queued_assets = deletion.delete_code_project(project.fingerprint)
    return {"deleted": result, "knowledge_assets_queued_for_deletion": queued_assets}

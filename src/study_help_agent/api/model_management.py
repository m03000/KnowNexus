"""桌面端模型管理 HTTP 接口。"""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from study_help_agent.api.dependencies import get_model_manager
from study_help_agent.infrastructure.models import ModelManager

router = APIRouter(prefix="/api/settings/models", tags=["模型管理"])
Manager = Annotated[ModelManager, Depends(get_model_manager)]


class ModelConfigurationUpdate(BaseModel):
    provider_id: str = Field(default="", max_length=80)
    name: str = Field(default="", max_length=80)
    provider: str = Field(default="openai-compatible", max_length=80)
    api_key: str = Field(default="", max_length=1000)
    base_url: str = Field(default="", max_length=1000)
    model: str = Field(default="", max_length=200)


@router.get("")
def get_configuration(manager: Manager): return manager.configuration()


@router.put("")
def save_configuration(request: ModelConfigurationUpdate, manager: Manager):
    try:
        return manager.save_configuration(request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/retrieval")
def get_retrieval_models(manager: Manager):
    return manager.retrieval_models()


@router.post("/retrieval/{kind}/install")
def install_retrieval_model(kind: str, manager: Manager):
    try:
        return manager.install_retrieval_model(kind)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"模型下载失败：{error}") from error


@router.post("/{provider_id}/activate")
def activate_provider(provider_id: str, manager: Manager):
    try:
        return manager.activate(provider_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{provider_id}")
def delete_provider(provider_id: str, manager: Manager):
    try:
        return manager.delete(provider_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

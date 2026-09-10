"""前端学习笔记展示的普通 HTTP 查询与删除接口。"""

from typing import Annotated, Literal

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
import shutil
import tempfile
import html

from study_help_agent.api.dependencies import (
    get_knowledge_deletion_service,
    get_learning_note_service,
)
from study_help_agent.capabilities.knowledge_ingestion.application.deletion_service import KnowledgeDeletionService
from study_help_agent.capabilities.learning_notes.application.service import LearningNoteService
from study_help_agent.core.config import get_settings
from study_help_agent.core.exceptions import LearningNoteNotFoundError


router = APIRouter(prefix="/api/library/notes", tags=["学习笔记展示"])
NoteService = Annotated[LearningNoteService, Depends(get_learning_note_service)]
DeletionService = Annotated[KnowledgeDeletionService, Depends(get_knowledge_deletion_service)]


class FolderCreateRequest(BaseModel):
    parent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)


class ItemMoveRequest(BaseModel):
    item_type: Literal["note", "document"]
    item_id: str = Field(min_length=1)
    folder_id: str = Field(min_length=1)


class ContentUpdateRequest(BaseModel):
    content: str = Field(max_length=10_000_000)


class ManualNoteCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    folder_id: str = Field(default="ai-note-root", min_length=1)


class MarkdownDocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    folder_id: str = Field(min_length=1)


class DocumentLinkRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
    name: str = Field(default="", max_length=255)
    media_type: str = Field(default="", max_length=255)
    folder_id: str = Field(default="personal-document-root", min_length=1)


class NoteExportRequest(BaseModel):
    export_format: Literal["md", "docx"]


@router.get("")
def list_notes(service: NoteService):
    """读取已经自动发布的笔记列表。"""

    return service.list_notes()


@router.get("/tree")
def get_library_tree(service: NoteService):
    """返回 AI 笔记与个人文档统一目录树。"""
    return service.library_tree()


@router.get("/dashboard")
def get_library_dashboard(service: NoteService):
    return service.dashboard()


@router.post("/folders")
def create_folder(request: FolderCreateRequest, service: NoteService):
    try:
        return service.create_folder(request.parent_id, request.name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, service: NoteService):
    try:
        service.delete_folder(folder_id)
        return {"message": "目录已删除"}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="目录不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.patch("/items/move")
def move_library_item(request: ItemMoveRequest, service: NoteService):
    try:
        service.move_library_item(request.item_type, request.item_id, request.folder_id)
        return {"message": "位置已更新"}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="内容或目录不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/documents")
def import_document(
    service: NoteService,
    file: UploadFile = File(...),
    folder_id: str = Form("personal-document-root"),
):
    """导入个人文档并自动提取文本、排队写入个人知识 RAG。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择文件")
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as stream:
        shutil.copyfileobj(file.file, stream)
        temporary = Path(stream.name)
    try:
        return service.import_document(
            temporary, Path(file.filename).name, file.content_type or "", folder_id
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        temporary.unlink(missing_ok=True)


@router.post("/documents/link")
def link_document(request: DocumentLinkRequest, service: NoteService):
    """关联本机原文件并入库；后端不复制文件。"""
    try:
        return service.link_document(
            request.source_path, request.name, request.media_type, request.folder_id
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="原文件不存在或已被移动") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/documents/markdown")
def create_markdown_document(request: MarkdownDocumentCreateRequest, service: NoteService):
    try:
        return service.create_markdown_document(request.title, request.folder_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/manual")
def create_manual_note(request: ManualNoteCreateRequest, service: NoteService):
    try:
        return service.create_manual_note(request.title, request.folder_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/documents/{document_id}/content")
def get_document_content(document_id: str, service: NoteService):
    try:
        return service.document_content(document_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="文档不存在") from error


@router.put("/documents/{document_id}/content")
def update_document_content(document_id: str, request: ContentUpdateRequest, service: NoteService):
    try:
        return service.update_document_content(document_id, request.content)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="文档不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/documents/{document_id}/reindex")
def reindex_document(document_id: str, service: NoteService):
    """增量重建一个文档；内容哈希未变化时不会重复切块和 Embedding。"""
    try:
        return service.reindex_document(document_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="文档不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/documents/{document_id}/analyze-knowledge")
def analyze_document_knowledge(document_id: str, service: NoteService):
    """仅在用户显式确认后提取文档知识点并写入笔记图谱。"""
    try:
        return service.analyze_document_knowledge(document_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="文档不存在或源文件已被移动") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, service: NoteService):
    """删除个人文档，并联动删除其关键词切块和向量索引。"""
    try:
        return service.delete_document(document_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="文档不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/documents/{document_id}")
def get_document(document_id: str, service: NoteService):
    try:
        document = service.document(document_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="文档不存在") from error
    media_type = document.get("media_type") or "application/octet-stream"
    path = Path(document["stored_path"])
    suffix = path.suffix.lower()
    preview_text = None
    if media_type.startswith("text/") or suffix in {".txt", ".md", ".markdown", ".html", ".htm"}:
        preview_text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".docx":
        try:
            from docx import Document
            preview_text = "\n\n".join(
                paragraph.text for paragraph in Document(path).paragraphs if paragraph.text.strip()
            )
        except (ImportError, OSError, ValueError):
            preview_text = "当前环境缺少 DOCX 预览依赖，可在新窗口中下载后查看。"
    if preview_text is not None:
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><style>body{max-width:920px;margin:36px auto;"
            "padding:0 28px;background:#fff;color:#202331;font:15px/1.8 system-ui;white-space:pre-wrap}"
            "</style><body>" + html.escape(preview_text) + "</body>"
        )
    disposition = "inline" if media_type.startswith(("text/", "image/", "application/pdf")) else "attachment"
    return FileResponse(
        document["stored_path"], media_type=media_type, filename=document["name"],
        content_disposition_type=disposition,
    )


@router.get("/source-files/{resource_id}")
def get_note_source_file(resource_id: str):
    """按内容指纹读取受控目录中永久保留的文档源文件。"""

    if not resource_id.startswith("resource_") or len(resource_id) != 33:
        raise HTTPException(status_code=404, detail="源文件不存在")
    expected = resource_id.removeprefix("resource_")
    root = (get_settings().runtime_data_directory / "learning_resources").resolve()
    if root.is_dir():
        for path in root.glob("*/*"):
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest().startswith(expected):
                return FileResponse(path, filename=path.name)
    raise HTTPException(status_code=404, detail="源文件不存在或已按临时资源策略清理")


@router.get("/{filename}")
def get_note(filename: str, service: NoteService):
    """读取一篇 Markdown 笔记正文。"""

    return service.read(filename)


@router.put("/{filename}")
def update_note(filename: str, request: ContentUpdateRequest, service: NoteService):
    """保存 AI 或手工 Markdown 笔记；自动保存阶段不触发知识点 LLM。"""
    try:
        return service.update(filename, request.content)
    except (FileNotFoundError, LearningNoteNotFoundError) as error:
        raise HTTPException(status_code=404, detail="笔记不存在") from error


@router.post("/{filename}/export")
def export_note(filename: str, request: NoteExportRequest, service: NoteService):
    try:
        return service.export_note(filename, request.export_format)
    except (FileNotFoundError, LearningNoteNotFoundError) as error:
        raise HTTPException(status_code=404, detail="笔记不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{filename}/segments")
def get_note_segments(filename: str, service: NoteService):
    """读取一篇 Markdown 笔记正文的某个段落。"""

    return service.read_with_segments(filename)


@router.delete("/{filename}")
def delete_note(
    filename: str,
    service: NoteService,
    deletion: DeletionService,
):
    """删除展示文件和片段，并可靠排队清理 RAG 索引。"""

    result = service.delete(filename)
    queued_assets = deletion.delete_note(filename)
    return {**result, "knowledge_assets_queued_for_deletion": queued_assets}

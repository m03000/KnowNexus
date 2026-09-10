"""把个人文档转换为可增量更新的个人知识资产。

该服务只负责“读取已经受控保存的文档、提取文本、提交规范知识资产”。切块、
Embedding、关键词索引和向量索引仍由统一的知识入库 Worker 异步完成。
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

from study_help_agent.capabilities.knowledge_ingestion.application.ports import (
    KnowledgeIngestionRepository,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.enums import (
    KnowledgeAssetType,
    KnowledgeSpace,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.models import (
    KnowledgeAssetDraft,
)
from study_help_agent.capabilities.learning_notes.application.resource_ports import (
    LearningContentExtractor,
)
from study_help_agent.capabilities.learning_notes.domain import AcquiredResource, ExtractedContent
from study_help_agent.capabilities.llm_wiki.application import WikiSourceService


logger = logging.getLogger(__name__)


class ImportedDocumentIngestionService:
    """为前端导入的文档建立稳定、幂等、可删除的 RAG 资产。"""

    SUPPORTED_SUFFIXES = {
        ".txt", ".md", ".markdown", ".csv", ".log", ".py", ".json",
        ".html", ".htm", ".docx", ".pdf",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    }

    def __init__(
        self,
        *,
        extractor: LearningContentExtractor,
        repository: KnowledgeIngestionRepository,
        wiki_sources: WikiSourceService | None = None,
    ) -> None:
        self._extractor = extractor
        self._repository = repository
        self._wiki_sources = wiki_sources

    def ingest(self, document: dict[str, Any]) -> dict[str, Any]:
        """提取文档文本并排队索引；同一文档内容未改变时自动跳过。"""

        document_id = str(document["document_id"])
        path, extracted, content = self.extract(document)
        wiki_source = None
        if self._wiki_sources is not None:
            try:
                wiki_source = self._wiki_sources.upsert_document(
                    document,
                    content,
                    extraction=dict(extracted.metadata),
                    warnings=list(extracted.warnings),
                ).as_dict()
            except Exception as error:
                logger.exception("Wiki 来源快照写入失败：%s", document_id)
                wiki_source = {"status": "failed", "error": str(error)}
        receipt = self._repository.upsert_and_enqueue(
            KnowledgeAssetDraft(
                space=KnowledgeSpace.PERSONAL_KNOWLEDGE,
                asset_type=KnowledgeAssetType.IMPORTED_DOCUMENT,
                stable_source_key=f"document:{document_id}",
                title=str(document.get("name") or path.name),
                content=content,
                metadata={
                    "document_id": document_id,
                    "source_kind": str(document.get("source_kind") or "import"),
                    "media_type": str(document.get("media_type") or ""),
                    "file_name": str(document.get("name") or path.name),
                    "extraction": dict(extracted.metadata),
                    "warnings": list(extracted.warnings),
                },
            )
        )
        result = {
            "asset_id": receipt.asset_id,
            "job_id": receipt.job_id,
            "queued": receipt.created,
            "skipped_reason": receipt.skipped_reason,
        }
        if wiki_source is not None:
            result["wiki_source"] = wiki_source
        return result

    def extract(self, document: dict[str, Any]) -> tuple[Path, ExtractedContent, str]:
        """复用统一解析器返回清洗后的正文，供 RAG 与显式知识点分析共用。"""

        document_id = str(document["document_id"])
        path = Path(str(document["stored_path"])).resolve(strict=True)
        if path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise ValueError(f"该文件类型暂不支持自动入库：{path.suffix or path.name}")
        extracted = self._extractor.extract(
            AcquiredResource(
                resource_id=document_id,
                local_path=str(path),
                source_uri=str(path),
                source_type="imported_document",
                media_type=str(document.get("media_type") or "application/octet-stream"),
                file_name=str(document.get("name") or path.name),
                size_bytes=int(document.get("size_bytes") or path.stat().st_size),
                metadata={
                    "document_id": document_id,
                    "source_kind": str(document.get("source_kind") or "import"),
                },
            )
        )
        content = self._clean_text(self._render_content(extracted))
        return path, extracted, content

    @staticmethod
    def _render_content(extracted: ExtractedContent) -> str:
        """把统一提取结果合成为保留结构的可检索文本，不调用 LLM 总结。"""

        sections: list[str] = []
        if extracted.text.strip():
            sections.append(extracted.text.strip())
        if extracted.audio_transcript:
            sections.append("## 音频文本\n\n" + "\n".join(
                f"[{item.start_seconds:.1f}-{item.end_seconds:.1f}] {item.text.strip()}"
                for item in extracted.audio_transcript if item.text.strip()
            ))
        if extracted.visual_transcript:
            sections.append("## 画面文字\n\n" + "\n".join(
                f"[{item.start_seconds:.1f}-{item.end_seconds:.1f}] {item.text.strip()}"
                for item in extracted.visual_transcript if item.text.strip()
            ))
        content = "\n\n".join(part for part in sections if part.strip()).strip()
        if not content:
            raise ValueError("文档未提取到可入库文本")
        return content

    @staticmethod
    def _clean_text(content: str) -> str:
        """执行低成本确定性清洗，只清除控制字符和异常空白，不总结或压缩原文。"""

        content = content.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        content = "\n".join(line.rstrip() for line in content.splitlines())
        return re.sub(r"\n{3,}", "\n\n", content).strip()

"""维护可追溯、可增量编译的 Wiki 标准化来源。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from study_help_agent.capabilities.llm_wiki.domain import (
    WikiSourceDraft,
    WikiSourceReceipt,
)
from study_help_agent.capabilities.llm_wiki.infrastructure.repository import (
    SqliteWikiRepository,
)


class WikiSourceService:
    """把异构来源固化为稳定 Markdown，并排队增量 Wiki 构建。"""

    def __init__(self, repository: SqliteWikiRepository, source_root: Path) -> None:
        self._repository = repository
        self._source_root = source_root.expanduser().resolve()

    def upsert(self, draft: WikiSourceDraft) -> WikiSourceReceipt:
        content = self._normalize_content(draft.title, draft.content)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = self._repository.get_source(draft.source_id)
        source_directory = self._directory_for(draft.source_id)
        normalized_path = source_directory / "content.md"
        version = int(existing["version"]) if existing else 0
        if (
            existing
            and existing["status"] == "active"
            and existing["content_hash"] == content_hash
            and normalized_path.exists()
        ):
            return WikiSourceReceipt(
                source_id=draft.source_id,
                version=version,
                content_hash=content_hash,
                normalized_path=str(normalized_path),
                queued=False,
                skipped_reason="content_unchanged",
            )

        version += 1
        source_directory.mkdir(parents=True, exist_ok=True)
        rendered = self._render_markdown(draft, content, content_hash, version)
        self._atomic_write(normalized_path, rendered)
        self._atomic_write(
            source_directory / "metadata.json",
            json.dumps(
                {
                    "source_id": draft.source_id,
                    "source_kind": draft.source_kind,
                    "source_ref": draft.source_ref,
                    "original_path": draft.original_path,
                    "title": draft.title,
                    "media_type": draft.media_type,
                    "content_hash": content_hash,
                    "version": version,
                    "status": "active",
                    "metadata": draft.metadata,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        self._repository.upsert_source(
            draft,
            normalized_path=str(normalized_path),
            content_hash=content_hash,
            version=version,
        )
        return WikiSourceReceipt(
            source_id=draft.source_id,
            version=version,
            content_hash=content_hash,
            normalized_path=str(normalized_path),
            queued=True,
        )

    def upsert_note(
        self,
        filename: str,
        title: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> WikiSourceReceipt:
        return self.upsert(
            WikiSourceDraft(
                source_id=f"note:{filename}",
                source_kind="generated_note",
                source_ref=filename,
                title=title,
                content=content,
                media_type="text/markdown",
                metadata=metadata or {},
            )
        )

    def upsert_document(
        self,
        document: dict[str, Any],
        content: str,
        *,
        extraction: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> WikiSourceReceipt:
        document_id = str(document["document_id"])
        return self.upsert(
            WikiSourceDraft(
                source_id=f"document:{document_id}",
                source_kind=str(document.get("source_kind") or "import"),
                source_ref=document_id,
                original_path=str(document.get("stored_path") or ""),
                title=str(document.get("name") or "个人文档"),
                content=content,
                media_type=str(document.get("media_type") or "application/octet-stream"),
                metadata={
                    "document_id": document_id,
                    "extraction": extraction or {},
                    "warnings": warnings or [],
                },
            )
        )

    def delete(self, source_id: str) -> bool:
        version = self._repository.mark_source_deleted(source_id)
        if version is None:
            return False
        source_directory = self._directory_for(source_id)
        (source_directory / "content.md").unlink(missing_ok=True)
        metadata_path = source_directory / "metadata.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                metadata = {"source_id": source_id}
            metadata.update({"status": "deleted", "version": version})
            self._atomic_write(
                metadata_path,
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        return True

    def _directory_for(self, source_id: str) -> Path:
        storage_key = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:24]
        return self._source_root / storage_key

    @staticmethod
    def _normalize_content(title: str, content: str) -> str:
        normalized = content.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if not re.match(r"^#\s+", normalized):
            normalized = f"# {title.strip()}\n\n{normalized}".rstrip()
        return normalized + "\n"

    @staticmethod
    def _render_markdown(
        draft: WikiSourceDraft,
        content: str,
        content_hash: str,
        version: int,
    ) -> str:
        front_matter = {
            "source_id": draft.source_id,
            "source_kind": draft.source_kind,
            "source_ref": draft.source_ref,
            "title": draft.title,
            "media_type": draft.media_type,
            "original_path": draft.original_path,
            "content_hash": content_hash,
            "version": version,
        }
        lines = ["---"]
        lines.extend(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in front_matter.items()
        )
        lines.extend(["---", "", content.rstrip(), ""])
        return "\n".join(lines)

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)

"""管理 LLM API 配置以及本地 Embedding/Reranker 权重。

运行期模型由桌面应用内置并保持 ``local_files_only``。用户只配置 LLM API Key；
聊天模型参数、Embedding 和 Reranker 均不能通过公开接口修改。
"""

from __future__ import annotations

import os
import json
import re
import uuid
from pathlib import Path
import tempfile
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.core.config import PROJECT_ROOT, Settings
from study_help_agent.infrastructure.llm.factory import reconfigure_chat_model


class ModelManager:
    """提供可审计的密钥保存和内置模型缓存检测。"""

    def __init__(self, settings: Settings, env_path: Path | None = None, llm: BaseChatModel | None = None) -> None:
        self._settings = settings
        self._env_path = env_path or PROJECT_ROOT / ".env"
        self._providers_path = self._env_path.with_name(".model-providers.json")
        self._llm = llm

    def configuration(self) -> dict[str, Any]:
        catalog = self._load_catalog()
        return {
            "providers": [self._public_provider(item) for item in catalog["providers"]],
            "active_provider_id": catalog.get("active_provider_id", ""),
            "restart_required": False,
        }

    def save_configuration(self, values: dict[str, Any]) -> dict[str, Any]:
        catalog = self._load_catalog()
        provider_id = self._safe_id(str(values.get("provider_id") or "")) or uuid.uuid4().hex[:12]
        existing = next((item for item in catalog["providers"] if item["provider_id"] == provider_id), None)
        api_key = str(values.get("api_key") or "").strip() or str((existing or {}).get("api_key") or "")
        base_url = str(values.get("base_url") or "").strip()
        model = str(values.get("model") or "").strip()
        name = str(values.get("name") or "").strip()
        if not api_key or not base_url or not model or not name:
            raise ValueError("供应商名称、API Key、Base URL 和模型名称均不能为空")
        provider = {
            "provider_id": provider_id,
            "name": name,
            "provider": str(values.get("provider") or "openai-compatible").strip(),
            "api_key": api_key,
            "base_url": base_url.rstrip("/"),
            "model": model,
        }
        catalog["providers"] = [item for item in catalog["providers"] if item["provider_id"] != provider_id]
        catalog["providers"].append(provider)
        catalog["active_provider_id"] = provider_id
        self._save_catalog(catalog)
        self._activate_values(provider)
        self._activate_runtime(provider)
        return self.configuration()

    def activate(self, provider_id: str) -> dict[str, Any]:
        catalog = self._load_catalog()
        provider = next((item for item in catalog["providers"] if item["provider_id"] == provider_id), None)
        if provider is None:
            raise ValueError("模型供应商不存在")
        if catalog.get("active_provider_id") == provider_id:
            return self.configuration()
        catalog["active_provider_id"] = provider_id
        self._save_catalog(catalog)
        self._activate_values(provider)
        self._activate_runtime(provider)
        return self.configuration()

    def delete(self, provider_id: str) -> dict[str, Any]:
        catalog = self._load_catalog()
        if catalog.get("active_provider_id") == provider_id:
            raise ValueError("不能删除当前激活的模型供应商")
        catalog["providers"] = [item for item in catalog["providers"] if item["provider_id"] != provider_id]
        self._save_catalog(catalog)
        return self.configuration()

    def _load_catalog(self) -> dict[str, Any]:
        if self._providers_path.exists():
            try:
                data = json.loads(self._providers_path.read_text(encoding="utf-8"))
                if isinstance(data.get("providers"), list):
                    return data
            except (OSError, ValueError):
                pass
        # Never expose or silently import process/.env credentials into the UI.
        # A provider exists only after the user explicitly saves one here.
        return {"active_provider_id": "", "providers": []}

    def _save_catalog(self, catalog: dict[str, Any]) -> None:
        self._atomic_write(self._providers_path, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")

    def _activate_values(self, provider: dict[str, Any]) -> None:
        self._replace_env_values({
            "LLM_API_KEY": str(provider["api_key"]),
            "LLM_BASE_URL": str(provider["base_url"]),
            "LLM_MODEL": str(provider["model"]),
        })

    def _activate_runtime(self, provider: dict[str, Any]) -> None:
        if self._llm is None:
            return
        reconfigure_chat_model(
            self._llm,
            self._settings,
            api_key=str(provider["api_key"]),
            base_url=str(provider["base_url"]),
            model_name=str(provider["model"]),
        )

    @staticmethod
    def _public_provider(provider: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in provider.items() if key != "api_key"
        } | {"api_key_configured": bool(provider.get("api_key"))}

    @staticmethod
    def _safe_id(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:80]

    def _model_info(self, kind: str) -> dict[str, Any]:
        model_id = self._model_id(kind)
        snapshot_path: Path | None = None
        try:
            from huggingface_hub import snapshot_download
            snapshot_path = Path(snapshot_download(repo_id=model_id, cache_dir=str(self._settings.rag_model_cache_directory), local_files_only=True))
            installed = True
        except Exception:
            installed = False
        size_bytes = 0
        if snapshot_path is not None:
            try:
                size_bytes = sum(item.stat().st_size for item in snapshot_path.rglob("*") if item.is_file())
            except OSError:
                size_bytes = 0
        return {"kind": kind, "model_id": model_id, "installed": installed,
                "size_bytes": size_bytes, "cache_directory": str(self._settings.rag_model_cache_directory)}

    def retrieval_models(self) -> dict[str, Any]:
        """Return the two fixed local retrieval models exposed by this release."""
        models = [self._model_info("embedding"), self._model_info("reranker")]
        return {"models": models, "ready": all(item["installed"] for item in models)}

    def install_retrieval_model(self, kind: str) -> dict[str, Any]:
        """Download one fixed model into the application cache."""
        model_id = self._model_id(kind)
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=model_id, cache_dir=str(self._settings.rag_model_cache_directory),
                          local_files_only=False)
        return self.retrieval_models()

    def _model_id(self, kind: str) -> str:
        if kind == "embedding":
            return self._settings.rag_embedding_model
        if kind == "reranker":
            return self._settings.rag_reranker_model
        raise ValueError("仅支持 embedding 或 reranker")

    def _replace_env_values(self, updates: dict[str, str]) -> None:
        lines = self._env_path.read_text(encoding="utf-8").splitlines() if self._env_path.exists() else []
        pending, result = dict(updates), []
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
            result.append(f"{key}={pending.pop(key)}" if key in pending else line)
        result.extend(f"{key}={value}" for key, value in pending.items())
        self._atomic_write(self._env_path, "\n".join(result).rstrip() + "\n")

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

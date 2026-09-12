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
import threading
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from openai import OpenAI

from study_help_agent.core.config import PROJECT_ROOT, Settings
from study_help_agent.infrastructure.llm.factory import reconfigure_chat_model


class ModelManager:
    """提供可审计的密钥保存和内置模型缓存检测。"""

    def __init__(self, settings: Settings, env_path: Path | None = None, llm: BaseChatModel | None = None) -> None:
        self._settings = settings
        self._env_path = env_path or Path(os.environ.get('KNOWNEXUS_CONFIG_DIRECTORY', str(PROJECT_ROOT))) / ".env"
        self._providers_path = self._env_path.with_name(".model-providers.json")
        self._llm = llm
        self._download_lock = threading.RLock()
        self._downloads: dict[str, dict[str, Any]] = {}
        self._restore_active_provider()

    _EXPECTED_MODEL_BYTES = {
        "embedding": 4_373 * 1024 * 1024,
        "reranker": 849 * 1024 * 1024,
    }

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

    def test_configuration(self, values: dict[str, Any]) -> dict[str, Any]:
        """Issue a minimal real request without persisting or exposing credentials."""
        catalog = self._load_catalog()
        provider_id = self._safe_id(str(values.get("provider_id") or ""))
        existing = next((item for item in catalog["providers"]
                         if item["provider_id"] == provider_id), None)
        api_key = str(values.get("api_key") or "").strip() or str((existing or {}).get("api_key") or "")
        base_url = str(values.get("base_url") or "").strip().rstrip("/")
        model = str(values.get("model") or "").strip()
        if not api_key or not base_url or not model:
            raise ValueError("请填写 API Key、Base URL 和模型名称后再测试")
        client = OpenAI(api_key=api_key, base_url=base_url,
                        timeout=min(self._settings.llm_timeout_seconds, 30), max_retries=0)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=8,
            temperature=0,
        )
        if not response.choices:
            raise RuntimeError("服务已响应，但没有返回任何候选结果")
        return {"ok": True, "message": "连接成功，API Key、接口地址和模型均可用"}

    def activate(self, provider_id: str) -> dict[str, Any]:
        catalog = self._load_catalog()
        provider = next((item for item in catalog["providers"] if item["provider_id"] == provider_id), None)
        if provider is None:
            raise ValueError("模型供应商不存在")
        if catalog.get("active_provider_id") != provider_id:
            catalog["active_provider_id"] = provider_id
            self._save_catalog(catalog)
        self._activate_values(provider)
        self._activate_runtime(provider)
        return self.configuration()

    def _restore_active_provider(self) -> None:
        """启动时把已保存的默认供应商恢复到共享对话模型。"""

        catalog = self._load_catalog()
        active_id = str(catalog.get("active_provider_id") or "")
        provider = next(
            (item for item in catalog["providers"] if item["provider_id"] == active_id),
            None,
        )
        if provider is not None:
            self._activate_values(provider)
            self._activate_runtime(provider)

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
            from .local_files import resolve_local_model
            snapshot_path = resolve_local_model(model_id, self._settings.rag_model_cache_directory)
            installed = True
        except Exception:
            installed = False
        size_bytes = 0
        if snapshot_path is not None:
            try:
                size_bytes = sum(item.stat().st_size for item in snapshot_path.rglob("*") if item.is_file())
            except OSError:
                size_bytes = 0
        downloaded_bytes = self._cached_model_bytes(model_id)
        with self._download_lock:
            download = dict(self._downloads.get(kind) or {})
        downloading = download.get("status") == "downloading"
        expected_bytes = int(download.get("expected_bytes") or self._EXPECTED_MODEL_BYTES[kind])
        progress = 1.0 if installed else min(0.98, downloaded_bytes / max(1, expected_bytes))
        return {"kind": kind, "model_id": model_id, "installed": installed,
                "size_bytes": size_bytes, "cache_directory": str(self._settings.rag_model_cache_directory),
                "model_path": str(snapshot_path) if snapshot_path else "",
                "downloading": downloading, "download_progress": progress,
                "downloaded_bytes": downloaded_bytes, "expected_bytes": expected_bytes}

    def _cached_model_bytes(self, model_id: str) -> int:
        """Count model blob bytes, including an in-progress ``.incomplete`` file."""
        folder = self._settings.rag_model_cache_directory / f"models--{model_id.replace('/', '--')}" / "blobs"
        if not folder.exists():
            return 0
        try:
            return sum(item.stat().st_size for item in folder.rglob("*") if item.is_file())
        except OSError:
            return 0

    def test_retrieval_model(self, kind: str) -> dict[str, Any]:
        """Keep native library crashes and memory exhaustion outside the server."""
        import subprocess
        import sys
        from .local_files import resolve_local_model
        folder = resolve_local_model(self._model_id(kind), self._settings.rag_model_cache_directory)
        command = ([sys.executable, '--knownexus-model-probe'] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'study_help_agent.infrastructure.models.probe'])
        try:
            result = subprocess.run(command + [kind, str(folder)], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=240,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('本地推理测试超过 4 分钟，请检查可用内存和模型文件') from exc
        marker = 'KNOWNEXUS_MODEL_TEST='
        for line in reversed(result.stdout.splitlines()):
            if line.startswith(marker) and result.returncode == 0:
                return {**self.retrieval_models(), 'test': json.loads(line[len(marker):])}
        details = (result.stderr or result.stdout).strip()[-1200:]
        raise RuntimeError(f'模型未能完成加载和推理（进程退出码 {result.returncode}）。请检查权重、运行依赖和可用内存。{details}')

    def _probe_retrieval_model(self, kind: str) -> dict[str, Any]:
        """Run a real, local-only inference, without downloading anything."""
        from .local_files import resolve_local_model
        import gc
        import numpy as np
        from sentence_transformers import SentenceTransformer, CrossEncoder

        folder = resolve_local_model(self._model_id(kind), self._settings.rag_model_cache_directory)
        model = None
        try:
            if kind == 'embedding':
                model = SentenceTransformer(str(folder), device='cpu', local_files_only=True)
                values = model.encode(['KnowNexus 本地模型测试'])
                if values.ndim != 2 or values.shape[1] == 0 or not np.isfinite(values).all():
                    raise ValueError('模型输出了无效向量')
                detail = f'本地加载及向量生成成功，维度 {values.shape[1]}'
            else:
                model = CrossEncoder(str(folder), device='cpu', local_files_only=True, max_length=512)
                values = model.predict([('What is KnowNexus?', 'KnowNexus is a knowledge workspace.')])
                if not np.isfinite(values).all():
                    raise ValueError('模型输出了无效分数')
                detail = '本地加载及重排评分成功'
            return {**self.retrieval_models(), 'test': {'ok': True, 'kind': kind, 'message': detail}}
        finally:
            del model
            gc.collect()

    def retrieval_models(self) -> dict[str, Any]:
        """Return the two fixed local retrieval models exposed by this release."""
        models = [self._model_info("embedding"), self._model_info("reranker")]
        return {"models": models, "ready": all(item["installed"] for item in models)}

    def install_retrieval_model(self, kind: str) -> dict[str, Any]:
        """Download one fixed model, falling back to the mirror on network errors."""
        model_id = self._model_id(kind)
        from huggingface_hub import snapshot_download

        download_options = {
            "repo_id": model_id,
            "cache_dir": str(self._settings.rag_model_cache_directory),
            "local_files_only": False,
            "ignore_patterns": [
                ".DS_Store",
                "**/.DS_Store",
                "imgs/*",
            ],
        }
        with self._download_lock:
            self._downloads[kind] = {
                "status": "downloading",
                "expected_bytes": self._EXPECTED_MODEL_BYTES[kind],
            }
        try:
            try:
                snapshot_download(**download_options, endpoint="https://huggingface.co")
            except Exception as exc:
                mirror = self._settings.rag_model_mirror_endpoint.strip().rstrip("/")
                if not mirror or not self._is_network_error(exc):
                    raise
                snapshot_download(**download_options, endpoint=mirror)
        finally:
            with self._download_lock:
                self._downloads.pop(kind, None)
        return self.retrieval_models()

    @staticmethod
    def _is_network_error(error: BaseException) -> bool:
        """Return whether an exception chain represents a connection failure."""
        current: BaseException | None = error
        visited: set[int] = set()
        network_error_names = {
            "ConnectError",
            "ConnectTimeout",
            "ConnectionError",
            "ConnectionResetError",
            "NetworkError",
            "ProxyError",
            "ReadTimeout",
            "TimeoutError",
        }
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if type(current).__name__ in network_error_names:
                return True
            if isinstance(current, OSError) and getattr(current, "winerror", None) in {
                10050, 10051, 10052, 10053, 10054, 10060, 10061, 10065,
            }:
                return True
            current = current.__cause__ or current.__context__
        return False

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

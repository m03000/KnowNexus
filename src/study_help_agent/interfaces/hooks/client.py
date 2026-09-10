"""Hook 到 personal_agent HTTP API 的轻量投递客户端。

Hook 进程无需加载主项目中的 LLM、Qdrant 等重依赖。
"""

from __future__ import annotations

import json
import os
from urllib import request

from .spool import HookSpool, SpoolTurn


class CaptureApiClient:
    """向本地捕获 API 投递轮次，并在成功后确认本地队列。"""

    def __init__(self, base_url: str | None = None, *, timeout: float = 1.5) -> None:
        self.base_url = (
            base_url or os.getenv("PERSONAL_AGENT_URL") or "http://127.0.0.1:8001"
        ).rstrip("/")
        self.timeout = timeout

    def send(self, turn: SpoolTurn) -> None:
        payload = {
            "client": "codex",
            "external_session_id": turn.session_id,
            "external_turn_id": turn.turn_id,
            "user_message": turn.prompt,
            "assistant_message": turn.assistant_message,
            "title": f"Codex {turn.session_id[:12]}",
            "cwd": turn.cwd,
            "model": turn.model,
            "transcript_path": turn.transcript_path,
            "metadata": turn.metadata,
        }
        self._post("/api/external-conversations/turns", payload)

    def flush_session(self, session_id: str) -> None:
        self._post(
            "/api/external-conversations/sessions/flush",
            {"client": "codex", "external_session_id": session_id},
        )

    def drain(self, spool: HookSpool) -> int:
        """按顺序投递就绪轮次；遇到后端故障立即停止并保留剩余记录。"""

        sent = 0
        for turn in spool.ready():
            try:
                self.send(turn)
            except Exception:
                break
            spool.acknowledge(turn)
            sent += 1
        return sent

    def _post(self, path: str, payload: dict) -> None:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        token = os.getenv("PERSONAL_AGENT_CAPTURE_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        call = request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(call, timeout=self.timeout) as response:
            if response.status >= 300:
                raise RuntimeError(f"capture API returned {response.status}")

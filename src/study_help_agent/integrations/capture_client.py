"""监听器共用的进程内对话投递客户端。"""
from __future__ import annotations

import logging

from study_help_agent.capabilities.external_conversation import ExternalConversationTurn
from study_help_agent.interfaces.hooks.spool import HookSpool, SpoolTurn

logger = logging.getLogger(__name__)


class InProcessCaptureClient:
    """把适配器暂存的完整轮次交给统一捕获服务。"""

    def __init__(self, service, on_capture=None, *, client_name: str = "codex") -> None:
        self._service = service
        self._on_capture = on_capture
        self._client_name = client_name

    def drain(self, spool: HookSpool) -> int:
        sent = 0
        for turn in spool.ready():
            try:
                domain_turn = self._to_domain(turn)
                result = self._service.capture_turn(domain_turn)
                if self._on_capture is not None:
                    self._on_capture(domain_turn, result)
            except Exception:
                logger.warning("Conversation remains queued after capture failure", exc_info=True)
                break
            spool.acknowledge(turn)
            sent += 1
        return sent

    def flush_session(self, session_id: str) -> None:
        self._service.flush_session(
            client=self._client_name, external_session_id=session_id,
        )

    def _to_domain(self, turn: SpoolTurn) -> ExternalConversationTurn:
        return ExternalConversationTurn(
            client=self._client_name,
            external_session_id=turn.session_id,
            external_turn_id=turn.turn_id,
            user_message=turn.prompt,
            assistant_message=turn.assistant_message,
            title=(str(turn.metadata.get("session_index_title") or "").strip()[:120]
                   or turn.prompt.replace("\n", " ").strip()[:60]
                   or f"{self._client_name} {turn.session_id[:12]}"),
            cwd=turn.cwd,
            model=turn.model,
            transcript_path=turn.transcript_path,
            metadata=turn.metadata,
        )

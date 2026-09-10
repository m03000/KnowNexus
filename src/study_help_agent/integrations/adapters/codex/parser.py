"""解析 Codex rollout JSONL，并只提取已完成的正式对话。

解析器忽略 developer/system 消息、commentary、reasoning 和工具调用。它以
task_started/task_complete 为轮次边界，因而不会把中间执行过程写入长期记忆。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import CapturedTurn


class CodexJsonlParser:
    """有状态地把 Codex 事件流组装成完整 CapturedTurn。"""

    def __init__(self, transcript_path: Path) -> None:
        self.transcript_path = transcript_path
        self.session_id = self._session_id_from_path(transcript_path)
        self.turn_id = ""
        self.prompt = ""
        self.final_answer = ""
        self.cwd = ""
        self.model = ""
        self.thread_source = ""
        self.session_source = ""

    @staticmethod
    def _session_id_from_path(path: Path) -> str:
        """从 rollout 文件名恢复 session id，支持从文件中部开始监听。"""

        match = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            path.stem,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else path.stem

    def feed(self, record: dict[str, Any]) -> CapturedTurn | None:
        """消费一条 JSONL 记录；仅在 task_complete 时返回完整轮次。"""

        top_type = str(record.get("type") or "")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None

        if top_type == "session_meta":
            self.session_id = str(payload.get("session_id") or payload.get("id") or "")
            self.cwd = str(payload.get("cwd") or self.cwd)
            self.thread_source = str(payload.get("thread_source") or "")
            source = payload.get("source")
            if isinstance(source, dict) and "subagent" in source:
                self.session_source = "subagent"
            else:
                self.session_source = str(source or "")
            return None

        if top_type == "turn_context":
            self.turn_id = str(payload.get("turn_id") or self.turn_id)
            self.cwd = str(payload.get("cwd") or self.cwd)
            self.model = str(payload.get("model") or self.model)
            return None

        if top_type == "response_item" and payload.get("type") == "message":
            role = str(payload.get("role") or "").casefold()
            content = _message_text(payload.get("content"))
            if role == "user" and self.turn_id and content:
                self.prompt = content
            elif role == "assistant" and content:
                # 新版 Codex 的最终答复位于 response_item；task_complete 仍是提交边界。
                if payload.get("phase") in {None, "", "final_answer"}:
                    self.final_answer = content
            return None

        if top_type != "event_msg":
            return None

        event_type = str(payload.get("type") or "")
        if event_type == "task_started":
            self._start_turn(str(payload.get("turn_id") or ""))
        elif event_type == "user_message" and self.turn_id:
            self.prompt = str(payload.get("message") or "").strip()
        elif event_type == "agent_message" and payload.get("phase") == "final_answer":
            self.final_answer = str(payload.get("message") or "").strip()
        elif event_type == "task_complete":
            return self._complete_turn(payload)
        return None

    def _start_turn(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self.prompt = ""
        self.final_answer = ""

    def _complete_turn(self, payload: dict[str, Any]) -> CapturedTurn | None:
        turn_id = str(payload.get("turn_id") or self.turn_id)
        answer = str(payload.get("last_agent_message") or self.final_answer).strip()
        if not self.session_id or not turn_id or not self.prompt or not answer:
            self._start_turn("")
            return None

        turn = CapturedTurn(
            session_id=self.session_id,
            turn_id=turn_id,
            prompt=self.prompt,
            assistant_message=answer,
            cwd=self.cwd,
            model=self.model,
            transcript_path=str(self.transcript_path),
            metadata={
                "capture_source": "codex_session_watcher",
                "completed_at": payload.get("completed_at"),
                "duration_ms": payload.get("duration_ms"),
                "codex_thread_source": self.thread_source,
                "codex_session_source": self.session_source,
            },
        )
        self._start_turn("")
        return turn


def _message_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_message_text(item) for item in value if item).strip()
    if isinstance(value, dict):
        return _message_text(value.get("text") or value.get("content") or "")
    return ""

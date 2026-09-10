"""DSH、TRAE 与 Claude Code 的独立会话解析器。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_help_agent.capabilities.external_conversation import ExternalConversationTurn
from study_help_agent.integrations.conversation_history import HistorySession
from study_help_agent.integrations.adapters.generic import GenericConversationParser


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_text(v.get("text") if isinstance(v, dict) else v) for v in value).strip()
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("content") or "")
    return ""


def _mtime(path: Path) -> float:
    try: return path.stat().st_mtime
    except OSError: return 0


def _iso(path: Path) -> str:
    return datetime.fromtimestamp(_mtime(path), timezone.utc).isoformat()


class ClaudeCodeConversationParser:
    """解析 ~/.claude/projects 中的完整 JSONL 会话。"""
    client = "claude_code"

    def __init__(self, root: Path) -> None: self.root = root.expanduser()

    def _files(self):
        return sorted(self.root.rglob("*.jsonl"), key=_mtime, reverse=True) if self.root.exists() else []

    def list_sessions(self, *, limit: int):
        result = []
        for path in self._files():
            turns = self._load(path)
            if turns:
                first = turns[0]
                result.append(HistorySession(self.client, first.external_session_id, first.title,
                    _iso(path), len(turns), first.cwd, str(path)))
            if len(result) >= limit: break
        return tuple(result)

    def load_session(self, session_id: str):
        for path in self._files():
            turns = self._load(path)
            if turns and turns[0].external_session_id == session_id: return turns
        raise ValueError("未找到指定 Claude Code 会话")

    def _load(self, path: Path):
        pending = None; answer = ""; turns = []; sid = path.stem; cwd = ""; model = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try: row = json.loads(line)
            except json.JSONDecodeError: continue
            if row.get("isSidechain"): continue
            sid = str(row.get("sessionId") or sid); cwd = str(row.get("cwd") or cwd)
            role = row.get("type"); message = row.get("message") or {}
            text = _text(message.get("content"))
            if role == "user" and text:
                if pending and answer: turns.append(self._turn(path, sid, cwd, model, pending, answer))
                pending = (str(row.get("uuid") or len(turns)), text); answer = ""
            elif role == "assistant" and pending and text:
                answer = f"{answer}\n{text}".strip(); model = str(message.get("model") or model)
        if pending and answer: turns.append(self._turn(path, sid, cwd, model, pending, answer))
        return tuple(turns)

    def _turn(self, path, sid, cwd, model, pending, answer):
        turn_id, prompt = pending
        return ExternalConversationTurn(client=self.client, external_session_id=sid,
            external_turn_id=turn_id, user_message=prompt, assistant_message=answer,
            title=prompt.replace("\n", " ")[:60], cwd=cwd, model=model,
            transcript_path=str(path), metadata={"capture_source": "claude_code_adapter"})


class DshConversationParser:
    """解压并解析 DSH session.jsonl.zstd 事件流。"""
    client = "dsh"
    def __init__(self, root: Path) -> None: self.root = root.expanduser()
    def _files(self):
        return sorted(self.root.rglob("session.jsonl.zstd"), key=_mtime, reverse=True) if self.root.exists() else []
    def _records(self, path):
        import zstandard
        with path.open("rb") as source:
            raw = zstandard.ZstdDecompressor().stream_reader(source).read().decode("utf-8", "replace")
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    def list_sessions(self, *, limit: int):
        result=[]
        for path in self._files():
            turns=self._load(path)
            if turns:
                first=turns[0]; result.append(HistorySession(self.client, first.external_session_id,
                    first.title, _iso(path), len(turns), first.cwd, str(path)))
            if len(result)>=limit: break
        return tuple(result)
    def load_session(self, session_id: str):
        for path in self._files():
            turns=self._load(path)
            if turns and turns[0].external_session_id==session_id: return turns
        raise ValueError("未找到指定 DSH 会话")
    def _load(self, path):
        sid=path.parent.name; cwd=""; title=""; pending=None; answers={}; turns=[]
        for row in self._records(path):
            kind=row.get("type"); data=row.get("data") or {}
            if kind=="session": sid=str(row.get("id") or sid); cwd=str(row.get("cwd") or "")
            elif kind=="session/title": title=str(data.get("title") or title)
            elif kind=="user/message" and (data.get("source") or {}).get("kind")=="user":
                if pending and answers.get(pending[0]): turns.append(self._turn(path,sid,cwd,title,pending,answers.pop(pending[0])))
                pending=(str(data.get("id") or row.get("seq")), _text(data.get("content")))
            elif kind=="assistant/message" and pending:
                message=data.get("message") or {}; text="\n".join(
                    _text(item) for item in message.get("content", []) if isinstance(item,dict) and item.get("type")=="text")
                if text: answers[pending[0]]=f"{answers.get(pending[0], '')}\n{text}".strip()
        if pending and answers.get(pending[0]): turns.append(self._turn(path,sid,cwd,title,pending,answers[pending[0]]))
        return tuple(turns)
    def _turn(self,path,sid,cwd,title,pending,answer):
        tid,prompt=pending
        return ExternalConversationTurn(client=self.client,external_session_id=sid,external_turn_id=tid,
            user_message=prompt,assistant_message=answer,title=title or prompt.replace("\n"," ")[:60],cwd=cwd,
            transcript_path=str(path),metadata={"capture_source":"dsh_adapter"})


class TraeConversationParser(GenericConversationParser):
    """TRAE 导出会话的独立适配器（JSON/JSONL）。"""
    def __init__(self, root: Path) -> None:
        super().__init__(root, client="trae")

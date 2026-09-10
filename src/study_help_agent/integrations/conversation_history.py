"""外部智能体历史会话发现、预览与幂等导入。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_help_agent.capabilities.external_conversation import ExternalConversationTurn
from study_help_agent.integrations.adapters.codex.parser import CodexJsonlParser


@dataclass(frozen=True, slots=True)
class HistorySession:
    """供前端选择的轻量会话摘要。"""
    client: str
    session_id: str
    title: str
    updated_at: str
    turn_count: int
    cwd: str
    transcript_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExternalHistoryService:
    """选择平台解析器并提供统一列表、预览和导入能力。"""
    def __init__(self, *, capture_service, parsers: dict[str, Any] | None = None,
                 codex_root: Path | None = None) -> None:
        self._capture_service = capture_service
        self._parsers = {key.strip().casefold(): value for key, value in (parsers or {}).items()}
        # Compatibility for internal callers/tests only. Public APIs always pass an
        # explicitly configured parser map and never probe a home directory.
        if codex_root is not None and not self._parsers:
            self._parsers["codex"] = CodexHistoryParser(codex_root)

    def list_sessions(self, *, client: str, limit: int = 30) -> list[dict[str, Any]]:
        return [{**item.to_dict(), "client": client} for item in self._parser(client).list_sessions(limit=limit)]

    def preview(self, *, client: str, session_id: str, limit: int = 20) -> dict[str, Any]:
        turns = self._parser(client).load_session(session_id)
        visible_turns = turns[-max(1, limit):]
        return {"client": client, "session_id": session_id, "turn_count": len(turns),
                "shown_count": len(visible_turns), "turns": [
            {"turn_id": turn.external_turn_id, "user_message": turn.user_message,
             "assistant_message": turn.assistant_message} for turn in visible_turns
        ]}

    def import_session(self, *, client: str, session_id: str) -> dict[str, Any]:
        turns = self._parser(client).load_session(session_id)
        results = [self._capture_service.capture_turn(turn, defer_consolidation=True) for turn in turns]
        internal_id = results[0].session_id if results else ""
        return {"client": client, "external_session_id": session_id,
                "session_id": internal_id, "total": len(results),
                "imported": sum(not item.duplicate for item in results),
                "duplicates": sum(item.duplicate for item in results)}

    def consolidate(self, session_id: str) -> None:
        if session_id:
            self._capture_service.consolidate_session_id(session_id=session_id, force=False)

    def _parser(self, client: str):
        normalized = client.strip().casefold()
        if normalized not in self._parsers:
            raise ValueError(f"暂不支持外部智能体：{client}")
        return self._parsers[normalized]


class CodexHistoryParser:
    """复用实时监听解析器读取 Codex rollout 历史。"""
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_sessions(self, *, limit: int) -> tuple[HistorySession, ...]:
        paths = sorted(self.root.rglob("rollout-*.jsonl"), key=_mtime, reverse=True)
        sessions = []
        for path in paths:
            turns = self._load(path)
            if not turns:
                continue
            first = turns[0]
            sessions.append(HistorySession("codex", first.external_session_id,
                _title(first.user_message), _iso_mtime(path), len(turns), first.cwd, str(path)))
            if len(sessions) >= limit:
                break
        return tuple(sessions)

    def load_session(self, session_id: str) -> tuple[ExternalConversationTurn, ...]:
        for path in self.root.rglob("rollout-*.jsonl"):
            if session_id in path.name:
                return self._load(path)
        raise ValueError("未找到指定 Codex 会话")

    @staticmethod
    def _load(path: Path) -> tuple[ExternalConversationTurn, ...]:
        parser, result = CodexJsonlParser(path), []
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    captured = parser.feed(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
                if captured is None:
                    continue
                source = str(captured.metadata.get("codex_thread_source") or "").casefold()
                if source == "subagent" or captured.prompt.casefold().startswith("the following is the codex agent history"):
                    continue
                result.append(ExternalConversationTurn(
                    client="codex", external_session_id=captured.session_id,
                    external_turn_id=captured.turn_id, user_message=captured.prompt,
                    assistant_message=captured.assistant_message, title=_title(captured.prompt),
                    cwd=captured.cwd, model=captured.model, transcript_path=str(path),
                    metadata=captured.metadata))
        if not result:
            return ()
        session_title = _title(result[0].user_message)
        return tuple(replace(turn, title=session_title) for turn in result)


class WorkBuddyHistoryParser:
    """解析 WorkBuddy sessions.json 索引与 projects 下的 JSONL 正文。"""
    def __init__(self, root: Path, *, index_path: Path | None = None,
                 projects_root: Path | None = None) -> None:
        self.root = root
        self.index_path = index_path or root / "app" / "sessions.json"
        self.projects_root = projects_root or root / "projects"

    def list_sessions(self, *, limit: int) -> tuple[HistorySession, ...]:
        entries = self._index()
        entries.sort(key=lambda item: str(item.get("resumedAt") or item.get("startedAt") or ""), reverse=True)
        result = []
        for entry in entries:
            sid = str(entry.get("conversationId") or "")
            path = self._find_transcript(sid)
            if path is None:
                continue
            turns = self._load(path, entry)
            if not turns:
                continue
            title = _workbuddy_session_title(entry, turns[0].user_message)
            result.append(HistorySession("workbuddy", sid, title,
                str(entry.get("resumedAt") or entry.get("startedAt") or _iso_mtime(path)),
                len(turns), str(entry.get("workDir") or ""), str(path)))
            if len(result) >= limit:
                break
        return tuple(result)

    def load_session(self, session_id: str) -> tuple[ExternalConversationTurn, ...]:
        entry = next((item for item in self._index() if item.get("conversationId") == session_id), {})
        path = self._find_transcript(session_id)
        if path is None:
            raise ValueError("未找到指定 WorkBuddy 会话正文")
        return self._load(path, entry)

    def _index(self) -> list[dict[str, Any]]:
        path = self.index_path
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in data.get("sessions", []) if isinstance(item, dict)]

    def _find_transcript(self, session_id: str) -> Path | None:
        matches = list(self.projects_root.glob(f"*/{session_id}.jsonl"))
        return matches[0] if matches else None

    @staticmethod
    def _load(path: Path, entry: dict[str, Any]) -> tuple[ExternalConversationTurn, ...]:
        records = []
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "message" and record.get("role") in {"user", "assistant"}:
                    records.append(record)
        sid, cwd = str(entry.get("conversationId") or path.stem), str(entry.get("workDir") or "")
        turns, pending, answer, model = [], None, "", ""
        for record in records:
            role, text = record.get("role"), _content_text(record.get("content"))
            if role == "user":
                if pending and answer:
                    turns.append(_workbuddy_turn(path, sid, pending, answer, cwd, model))
                cleaned = _clean_workbuddy_user(text)
                pending = (str(record.get("id") or len(turns)), cleaned) if cleaned else None
                answer = ""
            elif pending and text.strip():
                answer = text.strip()
                provider = record.get("providerData") or {}
                model = str(provider.get("requestModelName") or provider.get("model") or model)
        if pending and answer:
            turns.append(_workbuddy_turn(path, sid, pending, answer, cwd, model))
        if not turns:
            return ()
        session_title = _workbuddy_session_title(entry, turns[0].user_message)
        return tuple(replace(turn, title=session_title) for turn in turns)


def _workbuddy_turn(path, sid, pending, answer, cwd, model):
    turn_id, prompt = pending
    return ExternalConversationTurn(client="workbuddy", external_session_id=sid,
        external_turn_id=turn_id, user_message=prompt, assistant_message=answer,
        title=_title(prompt), cwd=cwd, model=model, transcript_path=str(path),
        metadata={"capture_source": "history_import"})


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(str(item.get("text") or "") for item in content
        if isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"}).strip()


def _clean_workbuddy_user(text: str) -> str:
    cleaned = re.sub(r"<system-reminder\b[^>]*>.*?</system-reminder>", "", text,
                     flags=re.DOTALL | re.IGNORECASE).strip()
    match = re.fullmatch(r"<user_query>\s*(.*?)\s*</user_query>", cleaned,
                         flags=re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else cleaned).strip()


def _title(text: str) -> str:
    return (re.sub(r"\s+", " ", text).strip()[:60] or "未命名会话")


def _workbuddy_session_title(entry: dict[str, Any], first_prompt: str) -> str:
    """优先使用 WorkBuddy 会话元数据；旧版本没有标题时使用工作区名。"""
    explicit = str(entry.get("title") or entry.get("name") or entry.get("conversationName") or "").strip()
    if explicit:
        return explicit
    cwd = str(entry.get("workDir") or "").strip().rstrip("/\\")
    if cwd:
        return Path(cwd).name
    return _title(first_prompt)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(_mtime(path), tz=timezone.utc).isoformat()

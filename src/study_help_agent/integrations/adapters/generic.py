"""声明式外部会话适配器：安全解析常见 JSON/JSONL 对话文件。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_help_agent.capabilities.external_conversation import ExternalConversationTurn
from study_help_agent.integrations.conversation_history import HistorySession


@dataclass(slots=True)
class GenericAdapterSchema:
    role_key: str = "role"
    content_key: str = "content"
    user_value: str = "user"
    assistant_value: str = "assistant"
    id_key: str = "id"
    session_key: str = "session_id"
    model_key: str = "model"
    messages_key: str = "messages"

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None):
        allowed = cls.__dataclass_fields__
        return cls(**{key: str(item) for key, item in (value or {}).items() if key in allowed and item})


class GenericConversationParser:
    def __init__(self, root: Path, schema: dict[str, Any] | None = None,
                 *, client: str = "generic") -> None:
        self.root = root.expanduser()
        self.schema = GenericAdapterSchema.from_dict(schema)
        self.client = client

    def list_sessions(self, *, limit: int) -> tuple[HistorySession, ...]:
        sessions = []
        for path in self._files()[: max(limit * 2, limit)]:
            turns = self._load(path)
            if not turns:
                continue
            first = turns[0]
            sessions.append(HistorySession(self.client, first.external_session_id,
                first.title, _mtime(path), len(turns), "", str(path)))
            if len(sessions) >= limit:
                break
        return tuple(sessions)

    def load_session(self, session_id: str) -> tuple[ExternalConversationTurn, ...]:
        for path in self._files():
            turns = self._load(path)
            if turns and turns[0].external_session_id == session_id:
                return turns
        raise ValueError("未找到指定会话")

    def preview(self, limit: int = 3) -> list[dict[str, str]]:
        result = []
        for session in self.list_sessions(limit=3):
            for turn in self.load_session(session.session_id)[-limit:]:
                result.append({"session_id": turn.external_session_id,
                    "user_message": turn.user_message[:500],
                    "assistant_message": turn.assistant_message[:800],
                    "model": turn.model})
        return result[-limit:]

    def _files(self) -> list[Path]:
        if self.root.is_file():
            return [self.root]
        if not self.root.exists():
            return []
        files = [*self.root.rglob("*.jsonl"), *self.root.rglob("*.json")]
        return sorted(set(files), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

    def _load(self, path: Path) -> tuple[ExternalConversationTurn, ...]:
        records = _records(path, self.schema.messages_key)
        pairs, pending = [], None
        session_id = path.stem
        for index, record in enumerate(records):
            role = str(_value(record, self.schema.role_key) or "").casefold()
            content = _text(_value(record, self.schema.content_key))
            if not content:
                continue
            record_session = _value(record, self.schema.session_key)
            if record_session:
                session_id = str(record_session)
            if role == self.schema.user_value.casefold():
                pending = (str(_value(record, self.schema.id_key) or index), content)
            elif role == self.schema.assistant_value.casefold() and pending:
                turn_id, prompt = pending
                pairs.append(ExternalConversationTurn(client=self.client,
                    external_session_id=session_id, external_turn_id=turn_id,
                    user_message=prompt, assistant_message=content,
                    title=prompt.replace("\n", " ")[:60],
                    model=str(_value(record, self.schema.model_key) or ""),
                    transcript_path=str(path), metadata={"capture_source": "generated_adapter"}))
                pending = None
        return tuple(pairs)


def infer_schema(sample_path: Path) -> dict[str, Any]:
    path = sample_path.expanduser()
    if path.is_dir():
        candidates = [*path.rglob("*.jsonl"), *path.rglob("*.json")]
        if not candidates:
            raise ValueError("目录中没有可分析的 JSON 或 JSONL 文件")
        path = max(candidates, key=lambda item: item.stat().st_mtime)
    if not path.is_file():
        raise ValueError("样本文件不存在")
    raw = _raw_records(path)
    messages_key = "messages"
    records = raw
    if len(raw) == 1 and isinstance(raw[0], dict):
        container = raw[0]
        for key in ("messages", "conversation", "history", "records", "items"):
            if isinstance(container.get(key), list):
                messages_key, records = key, container[key]
                break
    objects = [item for item in records if isinstance(item, dict)]
    if not objects:
        raise ValueError("样本中未发现结构化消息记录")
    keys = {key for item in objects[:100] for key in item}
    role_key = next((key for key in ("role", "sender", "author", "speaker", "type") if key in keys), "role")
    content_key = next((key for key in ("content", "text", "message", "body", "value") if key in keys), "content")
    roles = {str(item.get(role_key, "")).casefold() for item in objects[:100]}
    user_value = next((value for value in ("user", "human", "request", "input") if value in roles), "user")
    assistant_value = next((value for value in ("assistant", "ai", "bot", "response", "output") if value in roles), "assistant")
    schema = {"role_key": role_key, "content_key": content_key,
        "user_value": user_value, "assistant_value": assistant_value,
        "id_key": next((key for key in ("id", "message_id", "uuid") if key in keys), "id"),
        "session_key": next((key for key in ("session_id", "conversation_id", "thread_id") if key in keys), "session_id"),
        "model_key": next((key for key in ("model", "model_name") if key in keys), "model"),
        "messages_key": messages_key}
    parser = GenericConversationParser(path, schema)
    preview = parser.preview(3)
    if not preview:
        raise ValueError("已识别字段，但没有形成完整的用户—助手问答对")
    return {"sample_path": str(path), "format": path.suffix.lower().lstrip("."),
        "schema": schema, "preview": preview}


def _raw_records(path: Path) -> list[Any]:
    if path.suffix.casefold() == ".jsonl":
        result = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, list) else [data]


def _records(path: Path, messages_key: str) -> list[dict[str, Any]]:
    raw = _raw_records(path)
    if len(raw) == 1 and isinstance(raw[0], dict) and isinstance(raw[0].get(messages_key), list):
        raw = raw[0][messages_key]
    return [item for item in raw if isinstance(item, dict)]


def _value(record: dict[str, Any], key: str) -> Any:
    value: Any = record
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_text(item.get("text") if isinstance(item, dict) else item) for item in value).strip()
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("content") or "")
    return ""


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return ""

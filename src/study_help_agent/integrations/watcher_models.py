"""外部智能体监听器共享的数据模型。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WatcherConfig:
    """监听实例的统一配置；解析差异仅由 adapter_id 决定。"""

    id: str
    name: str
    parser_type: str
    adapter_id: str = ""
    enabled: bool = True
    session_index_path: str = ""
    conversation_root: str = ""
    memory_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WatcherConfig":
        parser_type = str(
            data.get("parser_type") or data.get("adapter_id") or "codex"
        ).casefold()
        conversation_root = str(data.get("conversation_root") or "")
        session_index_path = str(data.get("session_index_path") or "")
        memory_path = str(data.get("memory_path") or "")
        if parser_type == "codex" and conversation_root:
            codex_root = Path(conversation_root).expanduser()
            base = codex_root.parent if codex_root.name.casefold() == "sessions" else codex_root
            session_index_path = session_index_path or str(base / "session_index.jsonl")
            memory_path = memory_path or str(base / "memories_1.sqlite")
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            name=str(data.get("name") or "外部智能体"),
            parser_type=parser_type,
            adapter_id=str(data.get("adapter_id") or parser_type).casefold(),
            enabled=bool(data.get("enabled", True)),
            session_index_path=session_index_path,
            conversation_root=conversation_root,
            memory_path=memory_path,
        )

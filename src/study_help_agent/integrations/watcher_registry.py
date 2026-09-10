"""最多三个外部智能体监听器的持久化注册中心。"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_help_agent.integrations.capture_client import InProcessCaptureClient
from study_help_agent.integrations.adapters.codex import (
    CaptureCheckpoint,
    CapturePolicy,
    CodexConversationAdapter,
)
from study_help_agent.integrations.conversation_history import WorkBuddyHistoryParser
from study_help_agent.integrations.adapters.file import FileConversationAdapter
from study_help_agent.integrations.adapters.generic import (
    GenericConversationParser,
    infer_schema,
)
from study_help_agent.integrations.adapters.agent_parsers import (
    ClaudeCodeConversationParser, DshConversationParser, TraeConversationParser,
)
from study_help_agent.integrations.watcher_statistics import WatcherStatisticsStore
from study_help_agent.integrations.watcher_models import WatcherConfig
from study_help_agent.interfaces.hooks.spool import HookSpool

logger = logging.getLogger(__name__)

# 兼容旧测试导入；运行实现统一使用中性的 FileConversationAdapter。
WorkBuddyConversationWatcher = FileConversationAdapter


class ExternalWatcherRegistry:
    """持久化配置并独立管理最多三个监听线程。"""
    MAX_WATCHERS = 3

    def __init__(self, *, settings, capture_service, database=None) -> None:
        self.settings = settings
        self.capture_service = capture_service
        self.config_path = settings.runtime_data_directory / "external_agent_watchers.json"
        self.adapter_path = settings.runtime_data_directory / "external_agent_adapters.json"
        self.checkpoint_root = settings.runtime_data_directory / "external_watcher_checkpoints"
        self.spool_root = settings.runtime_data_directory / "external_watcher_spools"
        self._lock = threading.RLock()
        self._configs = {item.id: item for item in self._load_configs()}
        self._adapters = {item["id"]: item for item in self._load_adapters()}
        self._runtimes: dict[str, dict[str, Any]] = {}
        self._statistics = WatcherStatisticsStore(database) if database is not None else None
        self._database = database

    def start_enabled(self) -> dict[str, Any]:
        for config in tuple(self._configs.values()):
            if config.enabled:
                self.start(config.id)
        return self.status()

    def start(self, watcher_id: str | None = None) -> dict[str, Any]:
        if watcher_id is None:
            return self.start_enabled()
        with self._lock:
            config = self._require(watcher_id)
            runtime = self._runtimes.get(watcher_id)
            if runtime and runtime["thread"].is_alive():
                return self.status()
            watcher = self._build_watcher(config)
            thread = threading.Thread(target=self._run, args=(watcher_id, watcher),
                name=f"external-watcher-{watcher_id}", daemon=True)
            self._runtimes[watcher_id] = {"watcher": watcher, "thread": thread,
                "last_error": "", "started_at": _now(), "stopped_at": "",
                "captured_turns": 0, "duplicate_turns": 0, "distillation_tokens": 0,
                "memory_points": 0, "entities": 0, "relations": 0,
                "sessions": set(), "last_capture_at": "", "scan_count": 0,
                "error_count": 0, "restart_count": 0,
                "pending_consolidations": self._pending_sessions_from_database(config),
                "last_consolidation_error": ""}
            self._runtimes[watcher_id].update({"saved_captured_turns": 0,
                "saved_duplicate_turns": 0, "saved_distillation_tokens": 0,
                "saved_scan_count": 0, "saved_error_count": 0,
                "saved_sessions": set(), "last_stats_flush": time.monotonic()})
            config.enabled = True
            self._save_configs()
            thread.start()
        return self.status()

    def stop(self, watcher_id: str | None = None, *, timeout: float = 10.0) -> dict[str, Any]:
        ids = [watcher_id] if watcher_id else list(self._runtimes)
        for item_id in ids:
            runtime = self._runtimes.get(item_id)
            if runtime:
                runtime["watcher"].request_stop()
        for item_id in ids:
            runtime = self._runtimes.get(item_id)
            if runtime and runtime["thread"].is_alive():
                runtime["thread"].join(max(0.0, timeout))
            if runtime:
                self._flush_statistics(item_id, force=True)
            if watcher_id and item_id in self._configs:
                self._configs[item_id].enabled = False
        if watcher_id:
            self._save_configs()
        return self.status()

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if len(self._configs) >= self.MAX_WATCHERS:
                raise ValueError("最多只能配置三个外部智能体监听器")
            config = WatcherConfig.from_dict(payload)
            self._validate(config)
            self._configs[config.id] = config
            self._save_configs()
        if config.enabled:
            self.start(config.id)
        return self.status()

    def adapters(self) -> dict[str, Any]:
        return {"adapters": list(self._adapters.values())}

    def generate_adapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        sample_path = str(payload.get("sample_path") or "").strip()
        if not name or not sample_path:
            raise ValueError("适配器名称和样本文件地址不能为空")
        inferred = infer_schema(Path(sample_path))
        adapter_id = f"adapter_{uuid.uuid4().hex[:12]}"
        adapter = {"id": adapter_id, "name": name, "parser_type": "generic",
            "builtin": False, "description": f"自动识别 {inferred['format'].upper()} 对话结构",
            "schema": inferred["schema"], "sample_path": inferred["sample_path"]}
        self._adapters[adapter_id] = adapter
        self._save_adapters()
        return {"adapter": adapter, "preview": inferred["preview"], **self.adapters()}

    def test_adapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        adapter_id = str(payload.get("adapter_id") or "")
        root = str(payload.get("conversation_root") or payload.get("sample_path") or "")
        adapter = self._adapters.get(adapter_id)
        if not adapter:
            raise ValueError("适配器不存在")
        self._validate_sources(payload, adapter)
        if adapter_id == "workbuddy":
            config = WatcherConfig.from_dict({**payload, "id": "preview", "name": "preview",
                "parser_type": "workbuddy", "adapter_id": "workbuddy", "enabled": False})
            parser = WorkBuddyHistoryParser(Path(config.session_index_path).parent.parent,
                index_path=Path(config.session_index_path), projects_root=Path(config.conversation_root))
        elif adapter_id == "codex":
            from study_help_agent.integrations.conversation_history import CodexHistoryParser
            parser = CodexHistoryParser(Path(root))
        elif adapter_id == "dsh":
            parser = DshConversationParser(Path(root))
        elif adapter_id == "trae":
            parser = TraeConversationParser(Path(root))
        elif adapter_id == "claude_code":
            parser = ClaudeCodeConversationParser(Path(root))
        else:
            parser = GenericConversationParser(Path(root), adapter.get("schema"), client=adapter_id)
        sessions = parser.list_sessions(limit=3)
        preview = []
        for session in sessions:
            turns = parser.load_session(session.session_id)
            if turns:
                turn = turns[-1]
                preview.append({"session_id": session.session_id, "title": session.title,
                    "user_message": turn.user_message[:500],
                    "assistant_message": turn.assistant_message[:800], "model": turn.model})
        return {"success": bool(preview), "session_count": len(sessions), "preview": preview,
            "message": "监听测试通过" if preview else "没有识别到完整的最近对话"}

    def update(self, watcher_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        old = self._require(watcher_id)
        merged = {**asdict(old), **payload, "id": watcher_id}
        config = WatcherConfig.from_dict(merged)
        self._validate(config)
        self.stop(watcher_id)
        self._configs[watcher_id] = config
        self._save_configs()
        if config.enabled:
            self.start(watcher_id)
        return self.status()

    def delete(self, watcher_id: str) -> dict[str, Any]:
        self.stop(watcher_id)
        self._configs.pop(watcher_id, None)
        self._runtimes.pop(watcher_id, None)
        self._save_configs()
        return self.status()

    def status(self) -> dict[str, Any]:
        watchers = []
        for config in self._configs.values():
            runtime = self._runtimes.get(config.id)
            running = bool(runtime and runtime["thread"].is_alive())
            watchers.append({**asdict(config), "running": running,
                "stopping": bool(running and runtime["watcher"].is_stopping) if runtime else False,
                "last_error": runtime["last_error"] if runtime else "",
                "started_at": runtime["started_at"] if runtime else "",
                "stopped_at": runtime["stopped_at"] if runtime else "",
                "captured_turns": runtime["captured_turns"] if runtime else 0,
                "duplicate_turns": runtime["duplicate_turns"] if runtime else 0,
                "conversation_count": len(runtime["sessions"]) if runtime else 0,
                "distillation_tokens": runtime["distillation_tokens"] if runtime else 0,
                "last_capture_at": runtime["last_capture_at"] if runtime else "",
                "scan_count": runtime["scan_count"] if runtime else 0,
                "error_count": runtime["error_count"] if runtime else 0,
                "restart_count": runtime["restart_count"] if runtime else 0})
            watchers[-1]["pending_consolidation_count"] = (
                len(runtime["pending_consolidations"]) if runtime else 0
            )
            watchers[-1]["last_consolidation_error"] = (
                runtime["last_consolidation_error"] if runtime else ""
            )
            watchers[-1].update(self._source_file_info(config))
            watchers[-1].update(self._memory_output_counts(config))
        return {"running": any(item["running"] for item in watchers),
                "active_count": sum(item["running"] for item in watchers),
                "max_watchers": self.MAX_WATCHERS, "watchers": watchers}

    def statistics(self, *, start_at: str = "", end_at: str = "") -> dict[str, Any]:
        """返回指定时间范围内的历史汇总，并合并尚未落库的当前增量。"""
        historical = self._statistics.query(start_at=start_at, end_at=end_at) if self._statistics else {}
        includes_now = not end_at or end_at > _now()
        items = []
        for config in self._configs.values():
            saved = historical.get(config.id, {})
            runtime = self._runtimes.get(config.id)
            item = {"id": config.id, "name": config.name,
                "adapter_id": config.adapter_id, "parser_type": config.parser_type,
                "active_seconds": int(saved.get("active_seconds") or 0),
                "captured_turns": int(saved.get("captured_turns") or 0),
                "duplicate_turns": int(saved.get("duplicate_turns") or 0),
                "distillation_tokens": int(saved.get("distillation_tokens") or 0),
                "conversation_count": int(saved.get("conversation_count") or 0),
                "scan_count": int(saved.get("scan_count") or 0),
                "error_count": int(saved.get("error_count") or 0),
                "last_saved_at": str(saved.get("last_saved_at") or ""),
                "running": bool(runtime and runtime["thread"].is_alive()),
                "last_capture_at": runtime["last_capture_at"] if runtime else "",
                "last_error": runtime["last_error"] if runtime else "",
                "pending_consolidation_count": len(runtime["pending_consolidations"]) if runtime else 0,
                "last_consolidation_error": runtime["last_consolidation_error"] if runtime else ""}
            if runtime and includes_now:
                item["captured_turns"] += runtime["captured_turns"] - runtime["saved_captured_turns"]
                item["duplicate_turns"] += runtime["duplicate_turns"] - runtime["saved_duplicate_turns"]
                item["distillation_tokens"] += runtime["distillation_tokens"] - runtime["saved_distillation_tokens"]
                item["scan_count"] += runtime["scan_count"] - runtime["saved_scan_count"]
                item["error_count"] += runtime["error_count"] - runtime["saved_error_count"]
                item["conversation_count"] += len(runtime["sessions"] - runtime["saved_sessions"])
                if item["running"]:
                    item["active_seconds"] += max(0, int(time.monotonic() - runtime["last_stats_flush"]))
            item.update(self._memory_output_counts(config))
            item.update(self._source_file_info(config))
            items.append(item)
        return {"start_at": start_at, "end_at": end_at,
            "active_count": sum(item["running"] for item in items), "watchers": items}

    def _build_watcher(self, config: WatcherConfig):
        adapter = self._adapters.get(config.adapter_id or config.parser_type)
        parser_type = str((adapter or {}).get("parser_type") or config.parser_type)
        poll_interval = getattr(
            self.settings, "external_watcher_poll_seconds",
            self.settings.codex_watcher_poll_seconds,
        )
        if parser_type == "codex":
            return CodexConversationAdapter(sessions_dir=Path(config.conversation_root),
                session_index_path=Path(config.session_index_path),
                memory_path=Path(config.memory_path),
                poll_interval=poll_interval,
                full_scan_interval=self.settings.codex_watcher_full_scan_seconds,
                active_file_window=self.settings.codex_watcher_active_window_seconds,
                policy=CapturePolicy.from_env(),
                checkpoint=CaptureCheckpoint(self.checkpoint_root / f"{config.id}.db"),
                spool=HookSpool(self.spool_root / f"{config.id}.db"),
                client=InProcessCaptureClient(self.capture_service,
                    on_capture=lambda turn, result: self._record_capture(config.id, turn, result)),
                on_scan=lambda captured, error: self._record_scan(config.id, error))
        if parser_type in {"workbuddy", "generic", "dsh", "trae", "claude_code"}:
            parsers = {"dsh": DshConversationParser, "trae": TraeConversationParser,
                       "claude_code": ClaudeCodeConversationParser}
            if parser_type == "workbuddy": parser = None
            elif parser_type in parsers: parser = parsers[parser_type](Path(config.conversation_root))
            else: parser = GenericConversationParser(Path(config.conversation_root),
                (adapter or {}).get("schema"), client=config.adapter_id or config.parser_type)
            return FileConversationAdapter(config=config,
                capture_service=self.capture_service,
                checkpoint_path=self.checkpoint_root / f"{config.id}.json",
                poll_interval=poll_interval,
                on_capture=lambda turn, result: self._record_capture(config.id, turn, result),
                on_scan=lambda captured, error: self._record_scan(config.id, error), parser=parser)
        raise ValueError(f"不支持的适配器类型：{parser_type}")

    def _run(self, watcher_id: str, watcher) -> None:
        try:
            watcher.run_forever()
        except Exception as exc:
            logger.exception("External watcher stopped: %s", watcher_id)
            self._runtimes[watcher_id]["last_error"] = str(exc)
        finally:
            self._runtimes[watcher_id]["stopped_at"] = _now()

    def _record_capture(self, watcher_id: str, turn, result) -> None:
        with self._lock:
            runtime = self._runtimes.get(watcher_id)
            if not runtime:
                return
            if result.duplicate:
                runtime["duplicate_turns"] += 1
                return
            runtime["captured_turns"] += 1
            runtime["sessions"].add(turn.external_session_id)
            runtime["last_capture_at"] = _now()
            consolidation = getattr(result, "consolidation", {}) or {}
            runtime["distillation_tokens"] += int(consolidation.get("tokens") or 0)
            runtime["memory_points"] += int(consolidation.get("memory_points") or 0)
            runtime["entities"] += int(consolidation.get("entities") or 0)
            runtime["relations"] += int(consolidation.get("relations") or 0)
            reason = str(consolidation.get("reason") or "")
            if consolidation.get("consolidated"):
                runtime["pending_consolidations"].discard(result.session_id)
                runtime["last_consolidation_error"] = ""
            elif "失败" in reason or reason == "consolidation_failed":
                runtime["pending_consolidations"].add(result.session_id)
                runtime["last_consolidation_error"] = reason

    def _record_scan(self, watcher_id: str, error: Exception | None) -> None:
        retry_sessions: tuple[str, ...] = ()
        with self._lock:
            runtime = self._runtimes.get(watcher_id)
            if not runtime:
                return
            runtime["scan_count"] += 1
            if error is not None:
                runtime["error_count"] += 1
                runtime["last_error"] = str(error)
            self._flush_statistics(watcher_id)
            if runtime["scan_count"] % 3 == 0:
                retry_sessions = tuple(runtime["pending_consolidations"])
        for session_id in retry_sessions:
            self._retry_consolidation(watcher_id, session_id)

    def _retry_consolidation(self, watcher_id: str, session_id: str) -> None:
        """失败后按三个扫描周期重试，避免一次模型格式错误永久丢失图谱。"""
        try:
            result = self.capture_service.consolidate_session_id(
                session_id=session_id, force=False
            )
            with self._lock:
                runtime = self._runtimes.get(watcher_id)
                if not runtime:
                    return
                if result.get("consolidated"):
                    runtime["distillation_tokens"] += int(result.get("tokens") or 0)
                    runtime["pending_consolidations"].discard(session_id)
                    runtime["last_consolidation_error"] = ""
                else:
                    runtime["last_consolidation_error"] = str(result.get("reason") or "等待重试")
        except Exception as exc:
            with self._lock:
                runtime = self._runtimes.get(watcher_id)
                if runtime:
                    runtime["last_consolidation_error"] = str(exc)

    def _pending_sessions_from_database(self, config: WatcherConfig) -> set[str]:
        """恢复重启前达到三轮但尚未成功蒸馏的外部会话。"""
        if self._database is None:
            return set()
        client = (config.adapter_id or config.parser_type).casefold()
        try:
            with self._database.connect() as connection:
                rows = connection.execute(
                    """SELECT c.session_id FROM conversations c
                       JOIN messages m ON m.session_id = c.session_id
                       WHERE c.origin_type = 'external' AND c.origin_client = ?
                         AND m.message_id > c.distilled_until_message_id
                       GROUP BY c.session_id
                       HAVING SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END) >= 3""",
                    (client,),
                ).fetchall()
            return {str(row["session_id"]) for row in rows}
        except Exception:
            logger.warning("Unable to restore pending consolidation sessions", exc_info=True)
            return set()

    def _memory_output_counts(self, config: WatcherConfig) -> dict[str, int]:
        if self._database is None:
            return {"memory_points": 0, "entities": 0, "relations": 0}
        client = (config.adapter_id or config.parser_type).casefold()
        try:
            with self._database.connect() as connection:
                points = int(connection.execute(
                    "SELECT COUNT(*) FROM memory_points WHERE origin_client = ? AND status = 'active'", (client,)).fetchone()[0])
                entities = int(connection.execute("""SELECT COUNT(DISTINCT e.entity_id) FROM memory_entities e
                    JOIN memory_relations r ON (r.source_type='entity' AND r.source_id=e.entity_id) OR (r.target_type='entity' AND r.target_id=e.entity_id)
                    JOIN memory_points m ON (r.source_type='memory_point' AND r.source_id=m.memory_id) OR (r.target_type='memory_point' AND r.target_id=m.memory_id)
                    WHERE m.origin_client=?""", (client,)).fetchone()[0])
                relations = int(connection.execute("""SELECT COUNT(DISTINCT r.relation_id) FROM memory_relations r
                    JOIN memory_points m ON (r.source_type='memory_point' AND r.source_id=m.memory_id) OR (r.target_type='memory_point' AND r.target_id=m.memory_id)
                    WHERE m.origin_client=?""", (client,)).fetchone()[0])
            return {"memory_points": points, "entities": entities, "relations": relations}
        except Exception:
            return {"memory_points": 0, "entities": 0, "relations": 0}

    @staticmethod
    def _source_file_info(config: WatcherConfig) -> dict[str, Any]:
        root = Path(config.conversation_root).expanduser()
        try:
            files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
            size = sum(path.stat().st_size for path in files)
            latest = max((path.stat().st_mtime for path in files), default=root.stat().st_mtime)
            return {"source_file_size": size,
                    "source_last_modified": datetime.fromtimestamp(latest, timezone.utc).isoformat()}
        except OSError:
            return {"source_file_size": 0, "source_last_modified": ""}

    def _flush_statistics(self, watcher_id: str, *, force: bool = False) -> None:
        if self._statistics is None:
            return
        runtime = self._runtimes.get(watcher_id)
        config = self._configs.get(watcher_id)
        if not runtime or not config:
            return
        now = time.monotonic()
        if not force and now - runtime["last_stats_flush"] < 300:
            return
        self._statistics.append(watcher_id=watcher_id, watcher_name=config.name,
            active_seconds=int(now - runtime["last_stats_flush"]),
            captured_turns=runtime["captured_turns"] - runtime["saved_captured_turns"],
            duplicate_turns=runtime["duplicate_turns"] - runtime["saved_duplicate_turns"],
            distillation_tokens=runtime["distillation_tokens"] - runtime["saved_distillation_tokens"],
            scan_count=runtime["scan_count"] - runtime["saved_scan_count"],
            error_count=runtime["error_count"] - runtime["saved_error_count"],
            sessions=runtime["sessions"] - runtime["saved_sessions"])
        runtime.update({"saved_captured_turns": runtime["captured_turns"],
            "saved_duplicate_turns": runtime["duplicate_turns"],
            "saved_distillation_tokens": runtime["distillation_tokens"],
            "saved_scan_count": runtime["scan_count"],
            "saved_error_count": runtime["error_count"],
            "saved_sessions": set(runtime["sessions"]), "last_stats_flush": now})

    def _load_configs(self) -> list[WatcherConfig]:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return [WatcherConfig.from_dict(item) for item in data.get("watchers", [])]
        except (OSError, json.JSONDecodeError, TypeError):
            default = WatcherConfig(id="codex-default", name="Codex", parser_type="codex",
                adapter_id="codex", enabled=bool(self.settings.codex_watcher_enabled),
                conversation_root=str(self.settings.codex_watcher_sessions_directory),
                session_index_path=str(Path(self.settings.codex_watcher_sessions_directory).parent / "session_index.jsonl"),
                memory_path=str(Path(self.settings.codex_watcher_sessions_directory).parent / "memories_1.sqlite"))
            return [default]

    def _save_configs(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1,
            "watchers": [asdict(item) for item in self._configs.values()]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)

    def _load_adapters(self) -> list[dict[str, Any]]:
        home = Path.home()
        def fields(*items):
            return [{"key": key, "label": label, "placeholder": placeholder,
                     "required": required} for key, label, placeholder, required in items]
        builtins = [
            {"id": "codex", "name": "Codex", "parser_type": "codex", "builtin": True,
             "description": "Codex rollout JSONL 会话", "fields": fields(
                 ("conversation_root", "会话目录", "Codex sessions 目录", True),
                 ("session_index_path", "会话索引", "session_index.jsonl", True),
                 ("memory_path", "记忆数据库", "memories_1.sqlite", True))},
            {"id": "workbuddy", "name": "WorkBuddy", "parser_type": "workbuddy", "builtin": True,
             "description": "WorkBuddy sessions.json 与 projects 会话", "fields": fields(
                 ("conversation_root", "会话目录", "WorkBuddy projects 目录", True),
                 ("session_index_path", "会话索引", "sessions.json", True),
                 ("memory_path", "记忆/辅助来源", "记忆文件或目录", True))},
            {"id":"dsh", "name":"DeepSeek Harness", "parser_type":"dsh", "builtin":True,
             "description":"DeepSeek Harness Zstandard 会话事件流", "fields":fields(
                 ("conversation_root", "DSH 会话目录", str(home/".dsh"/"sessions"), True),
                 ("session_index_path", "工作区索引（可选）", str(home/".dsh"/"storages"/"workspace.json"), False),
                 ("memory_path", "会话投影缓存（可选）", str(home/".dsh"/"storages"/"session_projcache.json"), False)),
             "defaults":{"conversation_root":str(home/".dsh"/"sessions")}},
            {"id":"trae", "name":"Trae", "parser_type":"trae", "builtin":True,
             "description":"TRAE 导出的 JSON/JSONL 完整会话", "fields":fields(
                 ("conversation_root", "TRAE 会话导出文件或目录", "选择 TRAE 导出的 JSON/JSONL", True),
                 ("memory_path", "TRAE 记忆目录（可选）", str(home/".trae-cn"/"memory"), False)),
             "defaults":{}},
            {"id":"claude_code", "name":"Claude Code", "parser_type":"claude_code", "builtin":True,
             "description":"Claude Code projects JSONL 完整会话", "fields":fields(
                 ("conversation_root", "Claude Code 会话目录", str(home/".claude"/"projects"), True),
                 ("session_index_path", "历史索引（可选）", str(home/".claude"/"history.jsonl"), False)),
             "defaults":{"conversation_root":str(home/".claude"/"projects")}},
        ]
        try:
            custom = json.loads(self.adapter_path.read_text(encoding="utf-8")).get("adapters", [])
        except (OSError, json.JSONDecodeError, TypeError):
            custom = []
        return builtins + [item for item in custom if isinstance(item, dict) and item.get("id")]

    def _save_adapters(self) -> None:
        self.adapter_path.parent.mkdir(parents=True, exist_ok=True)
        custom = [item for item in self._adapters.values() if not item.get("builtin")]
        temporary = self.adapter_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "adapters": custom},
            ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.adapter_path)

    def _require(self, watcher_id: str) -> WatcherConfig:
        if watcher_id not in self._configs:
            raise ValueError("监听器不存在")
        return self._configs[watcher_id]

    def _validate(self, config: WatcherConfig) -> None:
        adapter = self._adapters.get(config.adapter_id or config.parser_type)
        if not adapter:
            raise ValueError("请选择有效的适配器")
        if not config.name.strip():
            raise ValueError("智能体名称不能为空")
        self._validate_sources(asdict(config), adapter)

    @staticmethod
    def _validate_sources(payload: dict[str, Any], adapter: dict[str, Any]) -> None:
        fields = adapter.get("fields") or [
            {"key":"conversation_root","label":"会话正文","required":True}]
        for field in fields:
            key, label = field["key"], field["label"]
            value = str(payload.get(key) or "").strip()
            if not value and field.get("required"):
                raise ValueError(f"{label}地址不能为空")
            if value and not Path(value).expanduser().exists():
                raise ValueError(f"{label}不存在：{value}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _turn_tokens(turn) -> int:
    metadata = getattr(turn, "metadata", {}) or {}
    usage = metadata.get("usage") or metadata.get("token_usage") or {}
    explicit = usage.get("total_tokens") or usage.get("totalTokens")
    if explicit:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass
    # 本地监听日志常不含 provider usage；中英文混合文本用字符数作保守估算。
    text = f"{turn.user_message}\n{turn.assistant_message}"
    cjk = sum('\u4e00' <= char <= '\u9fff' for char in text)
    return max(1, cjk + (len(text) - cjk) // 4)

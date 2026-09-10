"""基于会话索引/文件的 WorkBuddy 与通用来源适配器。"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from study_help_agent.integrations.conversation_history import WorkBuddyHistoryParser
from study_help_agent.integrations.polling_watcher import PollingConversationWatcher
from study_help_agent.integrations.watcher_models import WatcherConfig

logger = logging.getLogger(__name__)


class FileConversationAdapter(PollingConversationWatcher):
    """读取适配器给出的会话列表，只捕获建立基线后的完整新轮次。"""

    def __init__(self, *, config: WatcherConfig, capture_service,
                 checkpoint_path: Path, poll_interval: float = 20.0,
                 on_capture=None, on_scan=None, parser=None) -> None:
        super().__init__(poll_interval=poll_interval, on_scan=on_scan)
        index = Path(config.session_index_path).expanduser()
        projects = Path(config.conversation_root).expanduser()
        root = index.parent.parent if index.name else Path.home() / ".workbuddy"
        self.parser = parser or WorkBuddyHistoryParser(
            root, index_path=index, projects_root=projects,
        )
        self.capture_service = capture_service
        self.checkpoint_path = checkpoint_path
        self._seen, self._primed = self._load_seen()
        self._on_capture = on_capture
        self._sources = tuple(Path(value).expanduser() for value in (
            config.conversation_root, config.session_index_path, config.memory_path
        ) if str(value).strip())

    def scan_once(self) -> int:
        self._verify_sources()
        captured = 0
        for session in self.parser.list_sessions(limit=20):
            turns = list(self.parser.load_session(session.session_id))
            path = Path(session.transcript_path)
            try:
                # 冷启动必须把当前能识别的全部轮次纳入基线；否则最后一个
                # 活跃轮次会在 15 秒后被误判成“监听后新增”。
                if self._primed and time.time() - path.stat().st_mtime < 15 and turns:
                    turns = turns[:-1]
            except OSError as exc:
                logger.warning("Conversation transcript unavailable: %s (%s)", path, exc)
                continue
            for turn in turns:
                key = f"{turn.external_session_id}:{turn.external_turn_id}"
                if key in self._seen:
                    continue
                if not self._primed:
                    self._seen.add(key)
                    continue
                result = self.capture_service.capture_turn(turn)
                if result.duplicate:
                    self.capture_service.consolidate_session_id(
                        session_id=result.session_id, force=False,
                    )
                if self._on_capture is not None:
                    self._on_capture(turn, result)
                if not result.duplicate:
                    captured += 1
                self._seen.add(key)
        self._primed = True
        self._save_seen()
        return captured

    def _verify_sources(self) -> None:
        for path in self._sources:
            if not path.exists():
                raise FileNotFoundError(f"监听来源不存在：{path}")
            path.stat()

    def _load_seen(self) -> tuple[set[str], bool]:
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(payload, list) or payload.get("version") != 2:
                return set(), False
            return set(payload.get("seen", [])), bool(payload.get("primed", False))
        except (OSError, json.JSONDecodeError, TypeError):
            return set(), False

    def _save_seen(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "version": 2, "primed": self._primed, "seen": sorted(self._seen),
        }, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.checkpoint_path)


# 兼容已有导入名称；实现本身不再把 WorkBuddy 当成特殊运行层。
WorkBuddyConversationWatcher = FileConversationAdapter

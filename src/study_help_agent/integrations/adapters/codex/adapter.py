"""Codex 本地会话来源适配器。

扫描器按固定间隔检查文件大小，仅在 rollout JSONL 增长时读取新增字节。完整轮次
先写入现有 HookSpool，再尝试投递，因此后端暂时离线不会造成记忆丢失。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from study_help_agent.interfaces.hooks.client import CaptureApiClient
from study_help_agent.interfaces.hooks.spool import HookSpool
from study_help_agent.integrations.polling_watcher import PollingConversationWatcher

from .checkpoint import CaptureCheckpoint
from .filters import CapturePolicy
from .models import FileRuntime
from .parser import CodexJsonlParser

logger = logging.getLogger(__name__)


def default_sessions_dir() -> Path:
    """返回 Codex 默认会话目录。"""

    return Path.home() / ".codex" / "sessions"


class CodexConversationAdapter(PollingConversationWatcher):
    """Codex rollout 数据源适配器；运行生命周期由公共轮询基类提供。"""

    def __init__(
        self,
        sessions_dir: Path | None = None,
        *,
        session_index_path: Path | None = None,
        memory_path: Path | None = None,
        poll_interval: float = 3.0,
        full_scan_interval: float = 60.0,
        active_file_window: float = 86_400.0,
        backfill: bool = False,
        policy: CapturePolicy | None = None,
        checkpoint: CaptureCheckpoint | None = None,
        spool: HookSpool | None = None,
        client: CaptureApiClient | None = None,
        on_scan=None,
    ) -> None:
        super().__init__(poll_interval=poll_interval, on_scan=on_scan)
        self.sessions_dir = (sessions_dir or default_sessions_dir()).expanduser()
        self._auxiliary_required = session_index_path is not None or memory_path is not None
        self.session_index_path = (session_index_path or self.sessions_dir.parent / "session_index.jsonl").expanduser()
        self.memory_path = (memory_path or self.sessions_dir.parent / "memories_1.sqlite").expanduser()
        self.full_scan_interval = max(self.poll_interval, full_scan_interval)
        self.active_file_window = max(self.full_scan_interval, active_file_window)
        self.backfill = backfill
        self.policy = policy or CapturePolicy.from_env()
        self.checkpoint = checkpoint or CaptureCheckpoint()
        self.spool = spool or HookSpool()
        self.client = client or CaptureApiClient(timeout=3.0)
        self._files: dict[Path, FileRuntime] = {}
        self._primed = False
        self._last_full_scan = 0.0
        self._session_titles: dict[str, str] = {}
        self._index_mtime_ns = -1

    def after_stop(self) -> None:
        sent = self.client.drain(self.spool)
        logger.info("Codex watcher stopped; flushed %s queued turns", sent)

    def scan_once(self) -> int:
        """执行一次非阻塞增量扫描，返回新捕获的完整轮次数。"""

        if not self.sessions_dir.exists():
            logger.warning("Codex sessions directory does not exist: %s", self.sessions_dir)
            return 0
        self._refresh_auxiliary_sources()

        captured = 0
        paths = self._paths_for_scan()
        for path in paths:
            try:
                runtime = self._files.get(path)
                if runtime is None:
                    runtime = self._open_runtime(path, existing_at_start=not self._primed)
                    self._files[path] = runtime
                captured += self._read_growth(runtime)
            except FileNotFoundError:
                self._files.pop(path, None)
                logger.info("Codex rollout disappeared; stopped tracking: %s", path)
            except (PermissionError, OSError) as exc:
                logger.warning("Cannot read Codex rollout yet: %s (%s)", path, exc)
            except Exception:
                logger.exception("Unexpected Codex rollout failure isolated to: %s", path)
        self._primed = True
        try:
            sent = self.client.drain(self.spool)
            if sent:
                logger.info("Delivered %s captured Codex turns", sent)
        except Exception:
            logger.exception("Codex capture delivery failed; turns remain in spool")
        return captured

    def _paths_for_scan(self) -> tuple[Path, ...]:
        """高频只看活跃文件和当天目录，低频做全目录发现兜底。"""

        now = time.monotonic()
        full_scan = not self._primed or now - self._last_full_scan >= self.full_scan_interval
        paths: set[Path] = set()
        if full_scan:
            try:
                paths.update(self.sessions_dir.rglob("rollout-*.jsonl"))
            except (PermissionError, OSError) as exc:
                logger.warning("Cannot discover all Codex sessions: %s", exc)
            self._last_full_scan = now
        else:
            # 兼容测试目录和旧版 Codex 将 rollout 直接写在 sessions 根目录的情况。
            try:
                paths.update(self.sessions_dir.glob("rollout-*.jsonl"))
            except (PermissionError, OSError) as exc:
                logger.warning("Cannot discover root Codex sessions: %s", exc)
            today = datetime.now()
            today_dir = self.sessions_dir / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
            if today_dir.exists():
                try:
                    paths.update(today_dir.glob("rollout-*.jsonl"))
                except (PermissionError, OSError) as exc:
                    logger.warning("Cannot discover today's Codex sessions: %s", exc)

        cutoff = time.time() - self.active_file_window
        for path in tuple(self._files):
            try:
                if path.stat().st_mtime >= cutoff:
                    paths.add(path)
                elif not full_scan:
                    self._files.pop(path, None)
            except FileNotFoundError:
                self._files.pop(path, None)
            except (PermissionError, OSError):
                paths.add(path)
        return tuple(sorted(paths))

    def _open_runtime(self, path: Path, *, existing_at_start: bool) -> FileRuntime:
        parser = CodexJsonlParser(path)
        self._seed_session_metadata(path, parser)
        saved = self.checkpoint.get(path)
        if saved is not None:
            offset = min(saved, path.stat().st_size)
        elif existing_at_start and not self.backfill:
            offset = path.stat().st_size
            self.checkpoint.set(path, offset)
        else:
            offset = 0
        return FileRuntime(path=path, offset=offset, parser=parser)

    @staticmethod
    def _seed_session_metadata(path: Path, parser: CodexJsonlParser) -> None:
        """读取首条 session_meta，使从文件末尾监听时也能识别子 Agent 会话。"""

        try:
            with path.open("rb") as stream:
                raw = stream.readline()
            if raw.endswith(b"\n"):
                record = json.loads(raw.decode("utf-8-sig"))
                if record.get("type") == "session_meta":
                    parser.feed(record)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            logger.debug("Codex session metadata is not ready: %s", path, exc_info=True)

    def _read_growth(self, runtime: FileRuntime) -> int:
        size = runtime.path.stat().st_size
        if size < runtime.offset:
            runtime.offset = 0
            runtime.parser = CodexJsonlParser(runtime.path)
        if size == runtime.offset:
            return 0

        captured = 0
        with runtime.path.open("rb") as stream:
            stream.seek(runtime.offset)
            while True:
                line_start = stream.tell()
                raw = stream.readline()
                if not raw:
                    break
                if not raw.endswith(b"\n") and stream.tell() >= size:
                    stream.seek(line_start)
                    break
                runtime.offset = stream.tell()
                try:
                    record = json.loads(raw.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning("Skipped invalid Codex JSONL line: %s:%s", runtime.path, line_start)
                    continue
                try:
                    turn = runtime.parser.feed(record)
                except Exception:
                    logger.exception(
                        "Skipped unparsable Codex event: %s:%s", runtime.path, line_start
                    )
                    continue
                if turn is None:
                    continue
                title = self._session_titles.get(turn.session_id, "")
                turn = replace(turn, metadata={**turn.metadata,
                    "session_index_title": title,
                    "session_index_verified": bool(title),
                    "memory_source": str(self.memory_path)})
                # task_complete 是稳定边界：无论策略是否接受，都推进检查点，避免重复判断。
                self.checkpoint.set(runtime.path, runtime.offset)
                allowed, reason = self.policy.allows(turn)
                if not allowed:
                    logger.info(
                        "Filtered Codex turn %s/%s: %s", turn.session_id, turn.turn_id, reason
                    )
                    continue
                self.spool.record_prompt(turn.prompt_event())
                self.spool.record_stop(turn.stop_event())
                captured += 1
                logger.info("Captured Codex turn %s/%s", turn.session_id, turn.turn_id)
        return captured

    def _refresh_auxiliary_sources(self) -> None:
        """检查三个绑定来源，并从索引补充可读的会话标题。"""

        if not self._auxiliary_required:
            return
        if not self.session_index_path.exists():
            raise FileNotFoundError(f"Codex 会话索引不存在：{self.session_index_path}")
        if not self.memory_path.exists():
            raise FileNotFoundError(f"Codex 记忆来源不存在：{self.memory_path}")
        mtime_ns = self.session_index_path.stat().st_mtime_ns
        self.memory_path.stat()
        if mtime_ns == self._index_mtime_ns:
            return
        titles: dict[str, str] = {}
        with self.session_index_path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session_id = str(item.get("id") or item.get("session_id") or "")
                title = str(item.get("thread_name") or item.get("title") or "").strip()
                if session_id and title:
                    titles[session_id] = title
        self._session_titles = titles
        self._index_mtime_ns = mtime_ns

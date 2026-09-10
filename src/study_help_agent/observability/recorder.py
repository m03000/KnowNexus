"""线程安全的 JSONL Trace 记录器与单次运行指标汇总器。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Mapping
from uuid import uuid4

from .context import current_trace
from .sanitization import sanitize

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ObservabilityRecorder:
    """把事件追加到每日 JSONL，并把每个 Run 聚合成独立 JSON。"""

    def __init__(self, directory: Path | None = None) -> None:
        configured = os.getenv("OBSERVABILITY_LOG_DIRECTORY", "").strip()
        self._directory = Path(configured) if configured else (
            directory or PROJECT_ROOT / "var" / "observability"
        )
        self._events_directory = self._directory / "events"
        self._runs_directory = self._directory / "runs"
        self._lock = Lock()
        self._started: dict[str, float] = {}
        self._summaries: dict[str, dict[str, Any]] = {}

    def start_run(
        self, *, run_id: str, trace_id: str, session_id: str, turn_id: str,
        request_text: str,
    ) -> None:
        """创建 Run 汇总并记录请求开始；请求正文仅保留有限摘要。"""

        with self._lock:
            self._started[run_id] = perf_counter()
            self._summaries[run_id] = {
                "schema_version": 1, "run_id": run_id, "trace_id": trace_id,
                "session_id": session_id, "turn_id": turn_id,
                "started_at": self._now(), "finished_at": None, "status": "running",
                "request_preview": sanitize(request_text, max_text=300),
                "agent_events": 0, "agent_iterations": 0,
                "tool_calls": 0, "tool_successes": 0, "tool_failures": 0,
                "tool_retries": 0, "cache_hits": 0,
                "llm_calls": 0, "llm_failures": 0,
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "llm_duration_ms": 0, "tool_duration_ms": 0,
                "estimated_cost": 0.0, "artifacts": [],
                "business_metrics": {}, "errors": [],
            }
        self.record("run_started", run_id=run_id, data={"request_preview": request_text})

    def record(
        self, event: str, *, run_id: str | None = None,
        data: Mapping[str, Any] | None = None, agent: str | None = None,
        status: str | None = None, duration_ms: int | None = None,
    ) -> None:
        """写入一条结构化事件，并同步更新可计算指标。"""

        context = current_trace()
        effective_run_id = run_id or context.run_id or "background"
        payload = sanitize(dict(data or {}))
        item = {
            "schema_version": 1, "event_id": uuid4().hex,
            "timestamp": self._now(), "event": event,
            "trace_id": context.trace_id or effective_run_id,
            "run_id": effective_run_id,
            "parent_run_id": context.parent_run_id or None,
            "session_id": context.session_id or None,
            "turn_id": context.turn_id or None,
            "agent": agent or context.agent or "system",
            "stage": context.stage or None, "status": status,
            "duration_ms": duration_ms, "data": payload,
        }
        with self._lock:
            self._ensure_directories()
            path = self._events_directory / f"{datetime.now().astimezone():%Y-%m-%d}.jsonl"
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            self._aggregate(effective_run_id, event, payload, status, duration_ms)

    def finish_run(
        self, *, run_id: str, status: str, iterations: int = 0,
        tool_calls: int = 0, artifact_ids: tuple[str, ...] = (), error: str = "",
    ) -> None:
        """结束 Run 并写入最终聚合文件，供前端测试后直接统计。"""

        with self._lock:
            started = self._started.get(run_id)
            elapsed = round((perf_counter() - started) * 1000) if started else None
        self.record(
            "run_finished", run_id=run_id, status=status, duration_ms=elapsed,
            data={"iterations": iterations, "tool_calls": tool_calls,
                  "artifact_ids": list(artifact_ids), "error": error},
        )
        with self._lock:
            summary = self._summaries.setdefault(run_id, {"run_id": run_id})
            summary.update({
                "finished_at": self._now(), "status": status, "duration_ms": elapsed,
                "agent_iterations": max(int(summary.get("agent_iterations", 0)), iterations),
            })
            if artifact_ids:
                summary["artifacts"] = list(dict.fromkeys([
                    *summary.get("artifacts", []), *artifact_ids,
                ]))
            if error:
                summary.setdefault("errors", []).append(sanitize(error, max_text=800))
            self._ensure_directories()
            (self._runs_directory / f"{self._safe_name(run_id)}.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )

    def _aggregate(
        self, run_id: str, event: str, data: Mapping[str, Any],
        status: str | None, duration_ms: int | None,
    ) -> None:
        summary = self._summaries.get(run_id)
        if summary is None:
            return
        if event.startswith("agent_") or event in {
            "thought_summary", "route", "skill_start", "skill_end",
        }:
            summary["agent_events"] += 1
        if event == "thought_summary":
            summary["agent_iterations"] = max(
                summary["agent_iterations"], int(data.get("iteration", 0) or 0)
            )
        if event == "tool_finished":
            summary["tool_calls"] += 1
            summary["tool_duration_ms"] += int(duration_ms or 0)
            if status in {"success", "partial"}:
                summary["tool_successes"] += 1
            else:
                summary["tool_failures"] += 1
            if data.get("retryable"):
                summary["tool_retries"] += 1
            if data.get("cache_hit") is True or data.get("cached") is True:
                summary["cache_hits"] += 1
            self._collect_business_metrics(summary["business_metrics"], data)
            for artifact_id in data.get("artifact_ids", []) or []:
                if artifact_id not in summary["artifacts"]:
                    summary["artifacts"].append(artifact_id)
        if event == "llm_finished":
            summary["llm_calls"] += 1
            summary["llm_duration_ms"] += int(duration_ms or 0)
            summary["input_tokens"] += int(data.get("input_tokens", 0) or 0)
            summary["output_tokens"] += int(data.get("output_tokens", 0) or 0)
            summary["total_tokens"] += int(data.get("total_tokens", 0) or 0)
            summary["estimated_cost"] = round(
                float(summary["estimated_cost"]) + float(data.get("estimated_cost", 0) or 0), 8
            )
            if status == "failed":
                summary["llm_failures"] += 1
        if status == "failed" and data.get("error"):
            summary["errors"].append(sanitize(data["error"], max_text=800))

    @classmethod
    def _collect_business_metrics(cls, target: dict[str, Any], value: Any, prefix: str = "") -> None:
        """从工具 payload 提取数值/布尔指标，不复制正文。"""

        markers = (
            "count", "total", "coverage", "ratio", "rate", "files", "blocks",
            "chunks", "resources", "notes", "points", "retrieved", "candidates",
            "citations", "indexed", "characters", "duration", "success", "failed",
            "retry", "cache_hit",
        )
        if isinstance(value, Mapping):
            for key, item in value.items():
                name = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(item, (bool, int, float)) and any(
                    marker in str(key).lower() for marker in markers
                ):
                    target[name] = item
                elif isinstance(item, Mapping):
                    cls._collect_business_metrics(target, item, name)

    def _ensure_directories(self) -> None:
        self._events_directory.mkdir(parents=True, exist_ok=True)
        self._runs_directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")

    @staticmethod
    def _safe_name(value: str) -> str:
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in value)


_RECORDER = ObservabilityRecorder()


def get_observability_recorder() -> ObservabilityRecorder:
    """返回进程内共享记录器。"""

    return _RECORDER

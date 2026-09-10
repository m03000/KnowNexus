"""进程内 Agent Run 注册表，负责状态查询、单任务取消和应用关闭收敛。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Condition, RLock

from study_help_agent.runtime.cancellation import CancellationToken


@dataclass(slots=True)
class ActiveAgentRun:
    run_id: str
    session_id: str
    turn_id: str
    token: CancellationToken
    status: str = "queued"
    started_at: str = ""
    finished_at: str = ""
    error: str = ""

    def public(self) -> dict:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "cancel_requested": self.token.cancelled,
            "cancel_reason": self.token.reason if self.token.cancelled else "",
        }


class AgentRunRegistry:
    """保存当前进程的任务句柄；结束记录保留到进程重启。"""

    def __init__(self) -> None:
        self._runs: dict[str, ActiveAgentRun] = {}
        self._lock = RLock()
        self._condition = Condition(self._lock)

    def create(self, *, run_id: str, session_id: str, turn_id: str) -> ActiveAgentRun:
        with self._condition:
            existing = self._runs.get(run_id)
            if existing and existing.status in {"queued", "running", "cancelling"}:
                raise ValueError(f"Agent Run仍在执行：{run_id}")
            run = ActiveAgentRun(
                run_id=run_id,
                session_id=session_id,
                turn_id=turn_id,
                token=CancellationToken(),
                started_at=datetime.now(UTC).isoformat(),
            )
            self._runs[run_id] = run
            return run

    def mark_running(self, run_id: str) -> None:
        self._set_status(run_id, "running")

    def finish(self, run_id: str, *, status: str, error: str = "") -> None:
        with self._condition:
            run = self._require(run_id)
            run.status = status
            run.error = error
            run.finished_at = datetime.now(UTC).isoformat()
            self._condition.notify_all()

    def cancel(self, run_id: str, *, reason: str = "用户请求停止") -> dict:
        with self._condition:
            run = self._require(run_id)
            if run.status not in {"completed", "failed", "cancelled"}:
                run.token.cancel(reason)
                run.status = "cancelling"
            return run.public()

    def get(self, run_id: str) -> dict:
        with self._lock:
            return self._require(run_id).public()

    def cancel_all(self, reason: str = "应用正在关闭") -> int:
        count = 0
        with self._condition:
            for run in self._runs.values():
                if run.status in {"queued", "running", "cancelling"}:
                    run.token.cancel(reason)
                    run.status = "cancelling"
                    count += 1
            self._condition.notify_all()
        return count

    def wait_for_idle(self, timeout: float) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: not any(
                    run.status in {"queued", "running", "cancelling"}
                    for run in self._runs.values()
                ),
                timeout=max(timeout, 0.0),
            )

    def _set_status(self, run_id: str, status: str) -> None:
        with self._condition:
            self._require(run_id).status = status
            self._condition.notify_all()

    def _require(self, run_id: str) -> ActiveAgentRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise KeyError(f"未知 Agent Run：{run_id}") from error

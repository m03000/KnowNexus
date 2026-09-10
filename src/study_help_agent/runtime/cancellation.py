"""Agent运行的协作式取消协议。"""

from __future__ import annotations

from threading import Event


class AgentCancelledError(RuntimeError):
    """执行链在安全边界观察到取消请求。"""


class CancellationToken:
    """可在线程、Agent、工具和图节点之间共享的取消信号。"""

    def __init__(self) -> None:
        self._event = Event()
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason or "任务已取消"

    def cancel(self, reason: str = "用户请求停止") -> None:
        if not self._event.is_set():
            self._reason = reason.strip() or "任务已取消"
            self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise AgentCancelledError(self.reason)


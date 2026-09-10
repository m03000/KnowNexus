"""所有外部智能体监听器共用的轮询生命周期。"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod


class PollingConversationWatcher(ABC):
    """统一停止、异常隔离、扫描回调和轮询间隔。"""

    def __init__(self, *, poll_interval: float, on_scan=None) -> None:
        self.poll_interval = max(1.0, poll_interval)
        self._on_scan = on_scan
        self._stop_event = threading.Event()
        self.last_error = ""
        self._logger = logging.getLogger(type(self).__module__)

    @property
    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    captured = self.scan_once()
                    self.last_error = ""
                    self._notify_scan(captured, None)
                except Exception as exc:
                    self.last_error = str(exc)
                    self._logger.warning(
                        "%s scan failed; retrying: %s",
                        type(self).__name__, exc, exc_info=True,
                    )
                    self._notify_scan(0, exc)
                self._stop_event.wait(self.poll_interval)
        finally:
            self.after_stop()

    def _notify_scan(self, captured: int, error: Exception | None) -> None:
        if self._on_scan is not None:
            self._on_scan(captured, error)

    def after_stop(self) -> None:
        """适配器可在停止后刷新自己的持久化缓冲。"""

    @abstractmethod
    def scan_once(self) -> int:
        """扫描并返回本轮新增完整对话数量。"""

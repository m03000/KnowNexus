"""线程安全 TTL 检索缓存。"""

from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from time import monotonic

from study_help_agent.capabilities.rag.domain.models import RetrievalResult


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    value: RetrievalResult
    expires_at: float


class InMemoryRetrievalCache:
    """按查询及检索参数缓存完整结果，过期后自动失效。"""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = Lock()

    @staticmethod
    def make_key(
        query: str,
        top_k: int,
        recall_k: int,
        history_context: str = "",
        index_revision: str = "",
    ) -> str:
        raw = (
            f"{query.strip().lower()}|history={history_context.strip().lower()}|"
            f"top={top_k}|recall={recall_k}|revision={index_revision}"
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> RetrievalResult | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= monotonic():
                del self._entries[key]
                return None
            return entry.value

    def set(self, key: str, value: RetrievalResult) -> None:
        with self._lock:
            self._entries[key] = _CacheEntry(
                value=value, expires_at=monotonic() + self._ttl_seconds
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

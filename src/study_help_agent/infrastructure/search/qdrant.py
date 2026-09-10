"""进程级本地 Qdrant 客户端提供者，避免同一路径被重复打开。"""

from pathlib import Path
from threading import Lock


class LocalQdrantClientProvider:
    """让检索器和索引写入器共享一个延迟加载的线程安全客户端。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._client = None
        self._lock = Lock()

    def get(self):
        """首次使用时创建客户端，之后复用同一实例。"""

        if self._client is None:
            with self._lock:
                if self._client is None:
                    from qdrant_client import QdrantClient

                    self._database_path.mkdir(parents=True, exist_ok=True)
                    self._client = QdrantClient(path=str(self._database_path))
        return self._client

    def close(self) -> None:
        """关闭客户端并释放 Windows 文件锁。"""

        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

"""检索与入库共同使用的搜索基础设施。"""

from .qdrant import LocalQdrantClientProvider

__all__ = ["LocalQdrantClientProvider"]

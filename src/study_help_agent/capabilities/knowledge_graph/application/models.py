from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryGraphQuery:
    query: str | None = None
    memory_type: str | None = None
    topic: str | None = None
    min_importance: int | None = None
    # 0 表示全量；正整数仍可用于搜索或调用方主动限制结果。
    limit: int = 0

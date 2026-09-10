"""Agent 执行过程的公开流式事件协议。"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """发送给 API/前端的安全事件，不包含模型隐藏思维链。"""

    event: str
    run_id: str
    data: Mapping[str, Any] = field(default_factory=dict)
    agent: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""

        return asdict(self)

"""日志脱敏与体积控制，防止密钥、完整正文和巨大参数进入日志。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_SENSITIVE_MARKERS = (
    "api_key", "apikey", "authorization", "cookie", "password", "secret",
    "access_token", "refresh_token", "bearer_token",
)


def sanitize(value: Any, *, max_text: int = 500, depth: int = 0) -> Any:
    """生成适合 JSON 日志的有限、安全副本。"""

    if depth > 4:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        normalized = value.replace("\x00", "")
        return normalized if len(normalized) <= max_text else normalized[:max_text] + "…"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:80]:
            key = str(raw_key)
            if any(marker in key.lower() for marker in _SENSITIVE_MARKERS):
                result[key] = "<redacted>"
            else:
                result[key] = sanitize(item, max_text=max_text, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [sanitize(item, max_text=max_text, depth=depth + 1) for item in list(value)[:80]]
    return sanitize(str(value), max_text=max_text, depth=depth + 1)

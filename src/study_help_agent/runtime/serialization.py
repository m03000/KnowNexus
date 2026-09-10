from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel


def to_serializable(value: Any) -> Any:
    """ 标准化领域对象返回 json 兼容数据 """

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    if is_dataclass(value) and not isinstance(value, type):
        return to_serializable(asdict(value))

    if isinstance(value, Mapping):
        return {
            str(key): to_serializable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            to_serializable(item)
            for item in value
        ]

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    return value
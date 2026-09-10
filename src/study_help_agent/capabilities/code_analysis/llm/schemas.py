"""代码解释 Agent 的结构化 LLM 输出模型。

这些模型不是 HTTP Schema。
它们约束的是 LLM 返回结果。
"""

import json
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)


class BlockExplanationItem(BaseModel):
    block_id: str
    explanation: str = Field(min_length=1)


class BlockBatchExplanationOutput(BaseModel):
    blocks: list[BlockExplanationItem] = Field(
        default_factory=list
    )

class FileContextOutput(BaseModel):
    """LLM 对一个文件职责的分析结果。"""

    file_role: str = Field(
        min_length=1,
        description=(
            "该文件在项目中的职责，用一句话来分析概括"
        ),
    )

    function_roles: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "函数、类或方法名称到职责说明的映射。"
            "必须返回 JSON 对象，不能返回 JSON 字符串。"
        ),
    )

    @field_validator("function_roles", mode="before")
    @classmethod
    def parse_stringified_mapping(
        cls,
        value: Any,
    ) -> Any:
        """兼容模型把 JSON 对象返回成字符串。"""

        if not isinstance(value, str):
            return value

        normalized_value = value.strip()

        if not normalized_value:
            return {}

        try:
            parsed_value = json.loads(
                normalized_value
            )
        except json.JSONDecodeError as error:
            raise ValueError(
                "function_roles 必须是 JSON 对象"
            ) from error

        if not isinstance(parsed_value, dict):
            raise ValueError(
                "function_roles 解析后必须是对象"
            )

        return parsed_value

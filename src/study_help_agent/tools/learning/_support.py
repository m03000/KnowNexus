"""Learning Provider 共用的 Artifact 与 JSON Schema 边界函数。"""

from __future__ import annotations

from typing import Any, TypeVar

from study_help_agent.runtime.tools import ToolExecutionContext, ToolResult


T = TypeVar("T")


def get_content(
    context: ToolExecutionContext,
    artifact_id: str,
    expected_type: type[T],
) -> T:
    """读取中间 Artifact，并校验实际 Python 内容类型。"""

    content = context.artifact_store.get(artifact_id).content
    if not isinstance(content, expected_type):
        raise TypeError(f"Artifact {artifact_id} 必须包含 {expected_type.__name__}")
    return content


def put_artifact(
    context: ToolExecutionContext,
    artifact_type: str,
    name: str,
    summary: str,
    content: Any,
) -> ToolResult:
    """保存完整学习产物，仅向下一轮返回轻量 Artifact ID。"""

    artifact = context.artifact_store.put(
        artifact_type=artifact_type,
        name=name[:120],
        summary=summary,
        content=content,
    )
    return ToolResult(
        summary=summary,
        payload={"artifact_id": artifact.artifact_id},
        artifact_ids=(artifact.artifact_id,),
    )


def empty_schema() -> dict[str, Any]:
    """构造无参数 JSON Schema。"""

    return {"type": "object", "properties": {}}


def string_schema(name: str) -> dict[str, Any]:
    """构造单字符串参数 JSON Schema。"""

    return {
        "type": "object",
        "properties": {name: {"type": "string"}},
        "required": [name],
    }


def integer_schema(name: str) -> dict[str, Any]:
    """构造单整数参数 JSON Schema。"""

    return {
        "type": "object",
        "properties": {name: {"type": "integer"}},
        "required": [name],
    }

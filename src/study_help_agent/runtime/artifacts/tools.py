"""把 Artifact Store 的读取能力包装成 Loop Tool。

Agent 每轮只看到轻量 ArtifactReference；需要查看完整产物时，通过本文件提供的工具按
ID 获取受长度限制的序列化预览，避免大对象无条件进入上下文。
"""

import json
from typing import Any, Mapping

from study_help_agent.runtime.serialization import to_serializable
from study_help_agent.runtime.tools.core import (
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


class ArtifactAccessTools:
    """提供读取单个 Artifact 元数据和内容预览的工具。"""

    def __init__(self, *, max_preview_characters: int = 12_000) -> None:
        """设置一次返回给 LLM 的最大序列化字符数。"""

        if max_preview_characters < 1:
            raise ValueError("max_preview_characters must be positive")
        self._max_preview_characters = max_preview_characters

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回 Artifact 读取工具定义。"""

        return (
            ToolDefinition(
                name="read_artifact",
                description="按 Artifact ID 读取元数据和受长度限制的内容预览。",
                parameters={
                    "type": "object",
                    "properties": {"artifact_id": {"type": "string"}},
                    "required": ["artifact_id"],
                },
                handler=self.read_artifact,
            ),
        )

    def read_artifact(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """读取完整产物，在 Observation 中只返回截断后的 JSON 预览。"""

        artifact = context.artifact_store.get(str(arguments["artifact_id"]))
        serialized = json.dumps(
            to_serializable(artifact.content),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        preview = serialized[: self._max_preview_characters]
        truncated = len(serialized) > len(preview)
        return ToolResult(
            summary=f"Read artifact {artifact.artifact_id} ({artifact.artifact_type})",
            payload={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "name": artifact.name,
                "summary": artifact.summary,
                "content_preview": preview,
                "truncated": truncated,
            },
            partial=truncated,
        )

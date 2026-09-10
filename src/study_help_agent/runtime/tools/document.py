"""把安全文档写入能力包装成 Loop Tool。

Agent 可以决定何时生成什么文档，但真实写入始终经过 AtomicTextDocumentWriter
的路径限制和原子替换；工具还能从已有文本 Artifact 取内容，减少大文本参数传输。
"""

from pathlib import Path
from typing import Any, Mapping, Protocol

from study_help_agent.runtime.tools.core import (
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


class TextDocumentWriter(Protocol):
    """定义 Runtime 写文档所需的最小端口，避免依赖具体业务模块。"""

    def write(self, *, relative_path: str, content: str) -> Path:
        """在受控根目录内写入文本并返回最终路径。"""
        ...


class DocumentOutputTools:
    """提供受控 Markdown 或文本文件写入工具。"""

    GENERATED_DOCUMENT_TYPE = "generated_document"

    def __init__(self, *, writer: TextDocumentWriter) -> None:
        """注入共享的确定性原子文档写入器。"""

        self._writer = writer

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回文档写入工具定义。"""

        return (
            ToolDefinition(
                name="write_analysis_document",
                description=(
                    "在允许输出目录中原子写入文档；content 和 "
                    "source_artifact_id 必须且只能提供一个。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "relative_path": {"type": "string"},
                        "content": {"type": "string"},
                        "source_artifact_id": {"type": "string"},
                    },
                    "required": ["relative_path"],
                },
                handler=self.write_document,
            ),
        )

    def write_document(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """从参数或文本 Artifact 获取内容，安全写入后生成文档 Artifact。"""

        direct_content = arguments.get("content")
        source_id = arguments.get("source_artifact_id")
        if (direct_content is None) == (source_id is None):
            raise ValueError("Provide exactly one of content or source_artifact_id")
        if source_id is not None:
            source = context.artifact_store.get(str(source_id))
            if not isinstance(source.content, str):
                raise TypeError("Source artifact content must be text")
            content = source.content
        else:
            content = str(direct_content)
        relative_path = str(arguments["relative_path"])
        path: Path = self._writer.write(
            relative_path=relative_path,
            content=content,
        )
        artifact = context.artifact_store.put(
            artifact_type=self.GENERATED_DOCUMENT_TYPE,
            name=relative_path,
            summary=f"Generated document at {relative_path}",
            content={"path": str(path), "content": content},
        )
        return ToolResult(
            summary=artifact.summary,
            payload={"path": str(path), "relative_path": relative_path},
            artifact_ids=(artifact.artifact_id,),
        )

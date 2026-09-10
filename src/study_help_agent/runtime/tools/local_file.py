"""为 Main Agent 提供受控的本地文本文件读取能力。

Main Agent 只用它核对短期记忆中提到的文件路径、文件名和少量文本内容；
真正的批量获取、格式提取和笔记生成仍委派给 Learning Agent。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from study_help_agent.runtime.tools.core import (
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


class LocalFileReadTools:
    """在允许根目录内安全读取单个文本文件并生成 Artifact。"""

    TEXT_SUFFIXES = {
        ".txt", ".md", ".markdown", ".json", ".jsonl", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".csv", ".py", ".js", ".ts", ".tsx",
        ".jsx", ".java", ".go", ".rs", ".html", ".css", ".sql",
    }

    def __init__(
        self,
        *,
        allowed_roots: list[Path],
        max_file_bytes: int = 256 * 1024,
    ) -> None:
        """保存路径白名单和单文件读取上限；空白名单沿用本地开发模式。"""

        self._allowed_roots = tuple(
            root.expanduser().resolve() for root in allowed_roots
        )
        self._max_file_bytes = max_file_bytes

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回供 Main Agent 选择的文件读取工具定义。"""

        return (
            ToolDefinition(
                name="read_local_text_file",
                description=(
                    "读取短期记忆或当前请求中已经出现的本地文本文件路径，用于核对文件名、"
                    "路径和少量内容，并生成 text_file Artifact。支持常见纯文本与源码格式；"
                    "不读取 docx、PDF、图片、音视频，也不替代 Learning Agent 的资源提取。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "需要核对的本地文件绝对路径。",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                handler=self.read_text_file,
            ),
        )

    def read_text_file(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """校验路径、大小和格式后读取文本，正文放入 Artifact，观察结果仅含预览。"""

        target = Path(str(arguments["path"])).expanduser().resolve(strict=True)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        if self._allowed_roots and not any(
            target.is_relative_to(root) for root in self._allowed_roots
        ):
            raise PermissionError("文件不在允许访问的根目录内")
        if target.suffix.lower() not in self.TEXT_SUFFIXES:
            raise ValueError("该格式不是可直接读取的纯文本文件，请委派 Learning Agent 提取")
        size = target.stat().st_size
        if size > self._max_file_bytes:
            raise ValueError(
                f"文件大小 {size} bytes，超过主 Agent 读取上限 {self._max_file_bytes} bytes"
            )

        try:
            content = target.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = target.read_text(encoding="gb18030")
        artifact = context.artifact_store.put(
            artifact_type="text_file",
            name=target.name,
            summary=f"已读取本地文本文件：{target.name}",
            content={"path": str(target), "text": content},
        )
        return ToolResult(
            summary=artifact.summary,
            payload={
                "artifact_id": artifact.artifact_id,
                "path": str(target),
                "file_name": target.name,
                "size_bytes": size,
                "preview": content[:2000],
            },
            artifact_ids=(artifact.artifact_id,),
        )

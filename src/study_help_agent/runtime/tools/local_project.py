"""用于验证自主探索能力的本地文件系统工具。

这两个工具只允许访问配置根目录内部：list_directory 查看目录，read_text_file 读取
文本并把完整内容存入 Artifact Store。它们用于验证 Agent 能自主定位项目入口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from study_help_agent.runtime.tools.core import (
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


class LocalProjectTools:
    """创建绑定到单个项目根目录的安全只读工具。"""

    def __init__(
        self,
        *,
        project_root: Path,
        max_entries: int = 200,
        max_file_bytes: int = 128 * 1024,
    ) -> None:
        """解析允许根目录，并设置目录和文件读取预算。"""

        self._project_root = project_root.expanduser().resolve()
        self._max_entries = max_entries
        self._max_file_bytes = max_file_bytes
        if max_entries < 1 or max_file_bytes < 1:
            raise ValueError("Local tool limits must be positive")

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回可以直接注册进 ToolRegistry 的两个工具定义。"""

        return (
            ToolDefinition(
                name="list_directory",
                description="列出项目根目录内某个目录的直接子项。",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=self.list_directory,
            ),
            ToolDefinition(
                name="read_text_file",
                description="读取项目根目录内的 UTF-8 文本文件并生成 Artifact。",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=self.read_text_file,
            ),
        )

    def list_directory(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """列出直接子项，并标记是否因为数量限制而被截断。"""

        del context
        target = self._resolve(str(arguments["path"]))
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        entries = sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        visible = entries[: self._max_entries]
        payload = {
            "path": self._relative(target),
            "entries": [
                {
                    "name": item.name,
                    "path": self._relative(item),
                    "type": "directory" if item.is_dir() else "file",
                }
                for item in visible
            ],
            "truncated": len(entries) > len(visible),
        }
        return ToolResult(
            summary=f"Listed {len(visible)} entries in {payload['path']}",
            payload=payload,
            partial=payload["truncated"],
        )

    def read_text_file(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """读取受限文本文件，把完整内容保存为 Artifact 并返回短预览。"""

        target = self._resolve(str(arguments["path"]))
        if not target.is_file():
            raise FileNotFoundError(str(target))
        size = target.stat().st_size
        if size > self._max_file_bytes:
            raise ValueError(
                f"File is {size} bytes, above limit {self._max_file_bytes}"
            )
        content = target.read_text(encoding="utf-8")
        relative_path = self._relative(target)
        artifact = context.artifact_store.put(
            artifact_type="text_file",
            name=relative_path,
            summary=f"Text content of {relative_path}",
            content=content,
        )
        return ToolResult(
            summary=f"Read {relative_path} ({size} bytes)",
            payload={
                "path": relative_path,
                "size_bytes": size,
                "preview": content[:2000],
            },
            artifact_ids=(artifact.artifact_id,),
        )

    def _resolve(self, relative_path: str) -> Path:
        """解析相对路径并阻止绝对路径和父目录穿越。"""

        value = relative_path.strip() or "."
        candidate = (self._project_root / value).resolve()
        try:
            candidate.relative_to(self._project_root)
        except ValueError as error:
            raise PermissionError("Path escaped project root") from error
        return candidate

    def _relative(self, path: Path) -> str:
        """把绝对路径转换成 Agent 更容易使用的 POSIX 相对路径。"""

        value = path.relative_to(self._project_root).as_posix()
        return value or "."

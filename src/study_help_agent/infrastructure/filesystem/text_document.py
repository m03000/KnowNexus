"""在受控根目录中原子写入 UTF-8 文本文档。

这是 Runtime 公共基础设施，不属于任何具体业务 Capability。它负责
路径边界、非空校验、目录创建和临时文件替换，不包含 LLM 或领域逻辑。
"""

from pathlib import Path
from uuid import uuid4


class AtomicTextDocumentWriter:
    """把文本安全、原子地写入配置的输出根目录。"""

    def __init__(self, *, output_root: Path) -> None:
        """保存解析后的输出根目录，后续文件不能越过该边界。"""

        self._output_root = output_root.expanduser().resolve()

    def write(self, *, relative_path: str, content: str) -> Path:
        """校验相对路径和内容，并以临时文件替换方式写入。"""

        if not content.strip():
            raise ValueError("Cannot write an empty document")
        value = relative_path.strip().replace("\\", "/")
        if not value:
            raise ValueError("relative_path cannot be empty")
        target = (self._output_root / value).resolve()
        try:
            target.relative_to(self._output_root)
        except ValueError as error:
            raise PermissionError("Document path escaped output root") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8", newline="\n")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

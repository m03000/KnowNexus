"""Python 源文件读取。"""

import tokenize
from pathlib import Path

from study_help_agent.core.exceptions import (
    SourceFileTooLargeError,
)


def read_python_source(
    file_path: str | Path,
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> str:
    """按照 Python 源文件编码声明读取源码。"""

    path = (
        Path(file_path)
        .expanduser()
        .resolve(strict=True)
    )

    file_size = path.stat().st_size

    if file_size > max_bytes:
        raise SourceFileTooLargeError(
            f"源码文件超过大小限制："
            f"{file_size} > {max_bytes} bytes，"
            f"文件：{path}"
        )

    with tokenize.open(path) as source_file:
        return source_file.read()
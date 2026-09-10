"""项目源码内容指纹。"""

import hashlib
from pathlib import Path

from study_help_agent.shared_kernel.source_code.models import (
    SourceFile,
)


def calculate_source_fingerprint(
    project_root: str | Path,
    source_files: list[SourceFile],
) -> str:
    """根据相对路径与文件内容计算稳定 SHA-256。"""

    root = (
        Path(project_root)
        .expanduser()
        .resolve()
    )

    digest = hashlib.sha256()

    ordered_files = sorted(
        source_files,
        key=lambda item: (
            item.relative_path.lower()
        ),
    )

    for source_file in ordered_files:
        absolute_path = (
            source_file.absolute_path.resolve()
        )

        if not absolute_path.is_relative_to(
            root
        ):
            raise ValueError(
                "源码文件不属于项目目录："
                f"{absolute_path}"
            )

        relative_path = (
            absolute_path
            .relative_to(root)
            .as_posix()
        )

        digest.update(
            relative_path.encode("utf-8")
        )
        digest.update(b"\0")

        with absolute_path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(
                    1024 * 1024
                ),
                b"",
            ):
                digest.update(chunk)

        digest.update(b"\0")

    return digest.hexdigest()
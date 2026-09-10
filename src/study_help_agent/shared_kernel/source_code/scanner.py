"""项目源码文件扫描。"""

import os
from pathlib import Path

from study_help_agent.core.exceptions import (
    SourceScanLimitError,
)
from study_help_agent.shared_kernel.source_code.models import (
    SourceFile,
)
from study_help_agent.shared_kernel.source_code.paths import (
    resolve_existing_directory,
)


IGNORED_DIRECTORY_NAMES = frozenset({
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
})


def scan_python_files(
    project_root: str | Path,
    *,
    max_files: int = 1000,
) -> list[SourceFile]:
    """递归扫描项目中的 Python 文件。"""

    if max_files < 1:
        raise ValueError(
            "max_files 必须大于等于 1"
        )

    root = resolve_existing_directory(
        project_root
    )

    result: list[SourceFile] = []

    for (
        current_root,
        directory_names,
        file_names,
    ) in os.walk(
        root,
        followlinks=False,
    ):
        directory_names[:] = [
            directory_name
            for directory_name in directory_names
            if (
                not directory_name.startswith(".")
                and directory_name
                not in IGNORED_DIRECTORY_NAMES
            )
        ]

        current_path = Path(current_root)

        for file_name in file_names:
            if not file_name.lower().endswith(
                ".py"
            ):
                continue

            absolute_path = (
                current_path / file_name
            ).resolve()

            relative_path = (
                absolute_path
                .relative_to(root)
                .as_posix()
            )

            result.append(
                SourceFile(
                    absolute_path=absolute_path,
                    relative_path=relative_path,
                    language="python",
                )
            )

            if len(result) > max_files:
                raise SourceScanLimitError(
                    "项目 Python 文件数量超过限制："
                    f"{max_files}"
                )

    return sorted(
        result,
        key=lambda item: (
            item.relative_path.lower()
        ),
    )
"""源码项目路径基础函数。"""

import os
from pathlib import Path


def normalize_project_path(
    project_path: str | Path,
) -> str:
    """返回适合数据库比较的规范化绝对路径。

    该函数只做路径标准化，不做权限校验。
    """

    raw_path = os.fspath(project_path)

    return os.path.normcase(
        os.path.realpath(
            os.path.abspath(
                os.path.expanduser(raw_path)
            )
        )
    )


def resolve_existing_directory(
    project_path: str | Path,
) -> Path:
    """解析并验证一个已经存在的目录。"""

    resolved = (
        Path(project_path)
        .expanduser()
        .resolve()
    )

    if not resolved.exists():
        raise ValueError(
            f"项目目录不存在：{project_path}"
        )

    if not resolved.is_dir():
        raise ValueError(
            f"提供的路径不是目录：{project_path}"
        )

    return resolved
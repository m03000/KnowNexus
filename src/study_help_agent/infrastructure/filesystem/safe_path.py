"""用户输入路径的安全解析。"""

from pathlib import Path

from study_help_agent.core.exceptions import (
    InvalidProjectPathError,
    ProjectAccessDeniedError,
)


# 安全沙箱。用户通过 API 传一个路径过来，不能读取服务器上的任何文件。
class SafeProjectPathResolver:
    """验证项目路径是否位于允许访问的根目录。"""

    def __init__(
        self,
        allowed_roots: list[Path],
    ) -> None:
        self._allowed_roots = [
            root.expanduser().resolve()
            for root in allowed_roots
        ]

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return tuple(self._allowed_roots)

    def resolve_directory(
        self,
        raw_path: str | Path,
    ) -> Path:
        """解析并验证用户提供的项目目录。"""

        try:
            candidate = (
                Path(raw_path)
                .expanduser()
                .resolve(strict=True)  # strict=True 表示路径必须真实存在，如果路径不存在，抛出 FileNotFoundError。
            )
        except (
            OSError,
            RuntimeError,
        ) as error:
            raise InvalidProjectPathError(
                f"无法解析项目路径：{raw_path}"
            ) from error

        if not candidate.is_dir():
            raise InvalidProjectPathError(
                f"项目路径不是目录：{raw_path}"
            )

        if (
            self._allowed_roots
            and not self._is_allowed(candidate)
        ):
            raise ProjectAccessDeniedError(
                f"不允许访问项目目录：{raw_path}"
            )

        return candidate

    def resolve_file_under(
        self,
        project_root: Path,
        raw_path: str | Path,
    ) -> Path:
        """验证文件确实位于指定项目目录下。"""

        root = project_root.resolve()

        try:
            candidate = (
                Path(raw_path)
                .expanduser()
                .resolve(strict=True)
            )
        except (
            OSError,
            RuntimeError,
        ) as error:
            raise InvalidProjectPathError(
                f"无法解析文件路径：{raw_path}"
            ) from error

        if not candidate.is_file():
            raise InvalidProjectPathError(
                f"路径不是文件：{raw_path}"
            )

        if not candidate.is_relative_to(root):
            raise ProjectAccessDeniedError(
                "禁止读取项目目录之外的文件"
            )

        return candidate

    def _is_allowed(
        self,
        candidate: Path,
    ) -> bool:
        return any(
            candidate.is_relative_to(root)
            for root in self._allowed_roots
        )
from pathlib import Path

from study_help_agent.infrastructure.filesystem.safe_path import (
    SafeProjectPathResolver,
)
from study_help_agent.capabilities.code_analysis.application.dto import (
    SourceProjectSnapshot,
)
from study_help_agent.capabilities.code_analysis.application.ports import (
    SourceProjectInspector,
)
from study_help_agent.shared_kernel.source_code.fingerprint import (
    calculate_source_fingerprint,
)
from study_help_agent.shared_kernel.source_code.scanner import (
    scan_python_files,
)


class FileSystemSourceProjectInspector(
    SourceProjectInspector
):
    """基于本地文件系统检查源码项目。"""

    def __init__(
        self,
        path_resolver: SafeProjectPathResolver,
    ) -> None:
        self._path_resolver = path_resolver

    def inspect(
        self,
        *,
        project_path: Path,
        max_files: int,
    ) -> SourceProjectSnapshot:
        # 项目路径校验
        project_root = self._path_resolver.resolve_directory(project_path)

        # 文件递归扫描
        source_files = scan_python_files(
            project_root,
            max_files=max_files,
        )

        # 文件指纹计算
        fingerprint = calculate_source_fingerprint(
            project_root,
            source_files,
        )

        # 返回 SourceProjectSnapshot 格式校验内容
        return SourceProjectSnapshot(
            project_root=project_root,
            source_files=source_files,
            fingerprint=fingerprint,
        )
"""代码解释应用层依赖接口。"""

from pathlib import Path
from typing import Protocol

from study_help_agent.capabilities.code_analysis.application.dto import (
    ExplainedFileContent,
    ProjectSummary,
    ProjectTreeFolder,
    SourceProjectSnapshot,
)
from study_help_agent.capabilities.code_analysis.domain.models import (
    ExplainedProject,
)


class CodeAnalysisRepository(Protocol):
    """代码解释持久化接口。

    Application 依赖这个接口，
    SQLite Repository 在 Infrastructure 中实现它。
    """

    def find_cached_project(
        self,
        project_path: str,
        fingerprint: str,
        analysis_fingerprint: str = "",
    ) -> ExplainedProject | None:
        ...

    def save_project(
        self,
        project: ExplainedProject,
    ) -> int:
        """保存完整项目并返回 project_id。"""
        ...

    def get_project(
        self,
        project_id: int,
    ) -> ProjectSummary | None:
        ...

    def list_projects(
        self,
    ) -> list[ProjectSummary]:
        ...

    def delete_project(
        self,
        project_id: int,
    ) -> str | None:
        """删除项目，返回项目路径。"""
        ...

    def get_project_tree(
        self,
        project_id: int,
    ) -> list[ProjectTreeFolder]:
        ...

    def get_file_content(
        self,
        project_id: int,
        file_path: str,
    ) -> ExplainedFileContent | None:
        ...

class SourceProjectInspector(Protocol):
    """检查源码项目并产生项目快照。

    Application 只依赖这个接口，
    不直接依赖本地磁盘的具体实现。
    """

    def inspect(
        self,
        *,
        project_path: Path,
        max_files: int,
    ) -> SourceProjectSnapshot:
        ...



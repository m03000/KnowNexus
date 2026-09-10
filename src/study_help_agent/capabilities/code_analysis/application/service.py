"""代码解析结果的只读查询与记录管理应用服务。"""

from study_help_agent.core.exceptions import (
    ExplainedFileNotFoundError,
    ProjectNotFoundError,
)
from study_help_agent.capabilities.code_analysis.application.dto import (
    DeleteProjectResult,
    ExplainedFileContent,
    ProjectSummary,
    ProjectTreeFolder,
)
from study_help_agent.capabilities.code_analysis.application.ports import (
    CodeAnalysisRepository,
)
from study_help_agent.capabilities.code_analysis.domain.models import ExplainedProject


class CodeAnalysisService:
    """组织代码解析历史查询和记录删除，不修改用户源码。"""

    def __init__(self, *, repository: CodeAnalysisRepository) -> None:
        """注入代码解析持久化端口。"""

        self._repository = repository

    def list_projects(self) -> list[ProjectSummary]:
        """查询当前可展示的代码解析项目。"""

        return self._repository.list_projects()

    def publish(self, project: ExplainedProject) -> int:
        """默认保存已经由代码分析图完成验收的项目解析结果。"""

        return self._repository.save_project(project)

    def find_cached_analysis(
        self,
        *,
        project_path: str,
        source_fingerprint: str,
        analysis_fingerprint: str,
    ) -> ExplainedProject | None:
        """只复用源码和分析请求双指纹都完全一致的完整结果。"""

        return self._repository.find_cached_project(
            project_path,
            source_fingerprint,
            analysis_fingerprint,
        )

    def get_project(self, project_id: int) -> ProjectSummary:
        """查询项目，不存在时抛出业务异常。"""

        self._validate_project_id(project_id)
        project = self._repository.get_project(project_id)
        if project is None:
            raise ProjectNotFoundError(f"代码解析项目不存在：{project_id}")
        return project

    def get_project_tree(self, project_id: int) -> list[ProjectTreeFolder]:
        """查询项目目录、文件和代码符号树。"""

        self.get_project(project_id)
        return self._repository.get_project_tree(project_id)

    def get_file_content(
        self,
        *,
        project_id: int,
        file_path: str,
    ) -> ExplainedFileContent:
        """查询源码快照及对应代码块解释。"""

        self.get_project(project_id)
        normalized = file_path.strip()
        if not normalized:
            raise ExplainedFileNotFoundError("文件路径不能为空")
        content = self._repository.get_file_content(
            project_id=project_id,
            file_path=normalized,
        )
        if content is None:
            raise ExplainedFileNotFoundError(
                f"项目中不存在指定源码文件：{normalized}"
            )
        return content

    def delete_project(self, project_id: int) -> DeleteProjectResult:
        """删除保存的解析记录，不触碰本地项目源码。"""

        self._validate_project_id(project_id)
        project_path = self._repository.delete_project(project_id)
        if project_path is None:
            raise ProjectNotFoundError(f"代码解析项目不存在：{project_id}")
        return DeleteProjectResult(project_id=project_id, project_path=project_path)

    @staticmethod
    def _validate_project_id(project_id: int) -> None:
        """拒绝无效主键，避免无意义数据库查询。"""

        if project_id < 1:
            raise ProjectNotFoundError(f"无效的项目 ID：{project_id}")

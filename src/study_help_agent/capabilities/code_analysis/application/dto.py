"""代码解释应用层输入输出对象。"""

from dataclasses import dataclass, field
from pathlib import Path

from study_help_agent.capabilities.code_analysis.domain.models import (
    CodeBlockExplanation,
    CodeSymbol,
    ExplanationProjectStatus,
)
from study_help_agent.shared_kernel.source_code.models import (
    SourceFile,
)


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """项目历史列表中的一项。"""

    project_id: int
    project_name: str
    project_path: str
    fingerprint: str
    status: ExplanationProjectStatus
    total_files: int
    total_blocks: int
    scanned_at: str
    project_summary: str = ""


@dataclass(frozen=True, slots=True)
class ProjectTreeFile:
    """项目文件树中的文件。"""

    file_name: str
    file_path: str
    file_role: str
    relative_path: str = ""
    symbols: list[CodeSymbol] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class ProjectTreeFolder:
    """项目文件树中的目录。"""

    folder: str
    files: list[ProjectTreeFile] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class ExplainedFileContent:
    """源码及对应代码块解释。"""

    file_name: str
    file_path: str
    file_role: str

    source_lines: list[str] = field(
        default_factory=list
    )

    blocks: list[CodeBlockExplanation] = field(
        default_factory=list
    )


@dataclass(frozen=True, slots=True)
class DeleteProjectResult:
    """删除项目用例的结果。"""

    project_id: int
    project_path: str


@dataclass(frozen=True, slots=True)
class SourceProjectSnapshot:
    """一次源码项目检查得到的稳定快照。

    它描述：
    1. 最终解析出的项目根目录；
    2. 本次扫描发现的源码文件；
    3. 这些源码文件对应的内容指纹。
    """

    project_root: Path
    source_files: list[SourceFile]
    fingerprint: str

    @property
    def total_files(self) -> int:
        return len(self.source_files)



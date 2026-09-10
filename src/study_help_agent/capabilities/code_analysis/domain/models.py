"""代码解释领域模型，表示业务概念。

本模块不依赖：
- FastAPI
- LangGraph
- SQLite
- ChatOpenAI
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ExplanationProjectStatus(StrEnum):
    """代码解释项目状态。"""

    PROCESSING = "processing"
    COMPLETED = "completed"
    STALE = "stale"
    FAILED = "failed"


class CodeBlockType(StrEnum):
    """可解释代码块类型。"""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    STATEMENT_GROUP = "block"


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    """文件树中展示的代码符号。"""

    name: str
    symbol_type: CodeBlockType
    start_line: int
    end_line: int
    parent_class: str = ""
    summary: str = ""

    def __post_init__(self) -> None:
        if self.start_line < 1:
            raise ValueError(
                "start_line 必须大于等于 1"
            )

        if self.end_line < self.start_line:
            raise ValueError(
                "end_line 不能小于 start_line"
            )


@dataclass(frozen=True, slots=True)
class CodeBlockExplanation:
    """一个代码块及其解释结果。"""

    code_name: str
    code_type: CodeBlockType
    line_start: int
    line_end: int
    explanation: str

    parent_class: str = ""
    docstring: str = ""
    full_code: str = ""

    def __post_init__(self) -> None:
        if not self.code_name.strip():
            raise ValueError(
                "code_name 不能为空"
            )

        if self.line_start < 1:
            raise ValueError(
                "line_start 必须大于等于 1"
            )

        if self.line_end < self.line_start:
            raise ValueError(
                "line_end 不能小于 line_start"
            )


@dataclass(slots=True)
class ExplainedSourceFile:
    """一个已经完成解释的源码文件。"""

    file_path: str
    relative_path: str
    source_text: str
    file_role: str

    blocks: list[CodeBlockExplanation] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        if not self.file_path.strip():
            raise ValueError(
                "file_path 不能为空"
            )

        if not self.relative_path.strip():
            raise ValueError(
                "relative_path 不能为空"
            )


@dataclass(slots=True)
class ExplainedProject:
    """完成或正在处理的项目解释。"""

    project_name: str
    project_path: str
    fingerprint: str
    status: ExplanationProjectStatus
    analysis_fingerprint: str = ""

    files: list[ExplainedSourceFile] = field(
        default_factory=list
    )

    project_summary: str = ""
    project_id: int | None = None
    scanned_at: datetime | None = None

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_blocks(self) -> int:
        return sum(
            len(source_file.blocks)
            for source_file in self.files
        )

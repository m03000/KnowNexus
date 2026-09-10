"""本地代码分析图的共享状态协议。

状态只保存节点之间需要交换的数据。输入、扫描证据、选择范围、解释结果、错误和
覆盖率都显式建模，因此图可以恢复、检查并返回部分成功，而不是把过程藏在函数栈中。
"""

from typing import Any, Literal, TypedDict

from study_help_agent.runtime.cancellation import CancellationToken


class CodeAnalysisState(TypedDict, total=False):
    """保存单文件或项目级代码分析在节点之间交换的数据。"""

    project_path: str
    target_file: str
    analysis_goal: str
    mode: Literal["project", "files", "file"]
    target_files: list[str]
    max_files: int
    project_name: str
    fingerprint: str
    snapshot: Any
    prepared_files: dict[str, dict[str, Any]]
    import_contexts: dict[str, dict[str, list[str]]]
    selected_paths: list[str]
    requested_paths: list[str]
    file_contexts: dict[str, dict[str, Any]]
    project_summary: str
    explained_files: list[dict[str, Any]]
    failed_paths: list[str]
    errors: list[str]
    retry_count: int
    expected_file_count: int
    expected_block_count: int
    completed_block_count: int
    missing_block_ids_by_file: dict[str, list[str]]
    structure_coverage: float
    block_coverage: float
    coverage: float
    completion_status: Literal["completed", "partial", "failed"]
    cancellation_token: CancellationToken

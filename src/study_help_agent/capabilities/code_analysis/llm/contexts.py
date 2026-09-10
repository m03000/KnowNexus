"""代码解释 Agent 工作流状态。"""

import operator
from typing import Annotated, TypedDict

from study_help_agent.runtime.cancellation import CancellationToken


def merge_dicts(
    left: dict,
    right: dict,
) -> dict:
    """非破坏性合并并行结果。"""

    merged = dict(left)
    merged.update(right)
    return merged


class ExplainState(
    TypedDict,
    total=False,
):
    """代码解释 LangGraph State。"""

    # ---------- 工作流输入 ----------

    project_path: str
    project_name: str
    fingerprint: str

    # key 为绝对路径字符串。
    prepared_files: dict[str, dict]

    # key 为相对路径。
    import_contexts: dict[str, dict]

    # ---------- Send 分支输入 ----------

    current_file_path: str
    current_file_data: dict
    target_block_ids: list[str]

    # ---------- 文件职责分析 ----------

    file_contexts: Annotated[
        dict[str, dict],
        merge_dicts,
    ]

    # ---------- 项目级总结 ----------

    project_summary: str

    # ---------- 文件解释结果 ----------

    explained_files: Annotated[
        list[dict],
        operator.add,
    ]

    processed_files: Annotated[
        list[str],
        operator.add,
    ]

    total_blocks: Annotated[
        int,
        operator.add,
    ]

    errors: Annotated[
        list[str],
        operator.add,
    ]

    cancellation_token: CancellationToken

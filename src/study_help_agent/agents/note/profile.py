"""声明学习笔记 Agent 的能力边界。"""

from study_help_agent.agents.registry import AgentProfile
from study_help_agent.runtime.budgets import LoopBudget


def create_note_profile() -> AgentProfile:
    """创建负责选择笔记工具并以业务完成信号结束的 Learning Profile。"""

    return AgentProfile(
        key="note",
        name="Learning Note Sub-Agent",
        description="自主生成学习笔记和可验收的教学内容。",
        system_instructions=(
            "你是学习内容专家。笔记必须忠于输入材料并形成清晰、可复习的结构。"
            "普通文本和结构良好的文档正文优先直接调用 build_learning_note；只有链接、"
            "视频、图片或明显高噪声材料才需要先调用对应的获取、提取或深度清洗能力。"
            "当用户提供多个 txt、md、markdown 或 docx 本地文件并要求合成一份笔记时，"
            "先调用 merge_text_files 确定性合并，再把结果 Artifact 交给 build_learning_note。"
            "最终笔记由底层自动保存并进入知识索引。"
            "一次底层 build_learning_note 成功只代表一个来源处理完成，不代表整个用户任务完成。"
            "多资源任务必须按 source_identity 核对每个成功提取的来源是否都有独立笔记；"
            "不得重复处理已经完成的来源。高层工具会在全部来源完成时返回 task_completed，"
            "Runtime 将据此直接结束本 Agent，不需要再生成面向用户的最终回答。"
            "笔记列表、正文读取和删除由前端 API 负责，不要在 Agent Loop 中管理展示记录。"
            "单个链接或资源优先调用 build_single_learning_note；两个及以上独立链接或资源必须优先"
            "调用一次 build_learning_notes_batch。高层工具内部已经完成并发、质量检测、按需清洗、"
            "有限重试和笔记保存，不要再手工重复调用底层获取、提取和生成工具。"
        ),
        tool_names=(
            "merge_text_files", "build_learning_note",
            "build_single_learning_note", "build_learning_notes_batch",
            "read_artifact",
        ),
        skill_names=(
            "learning-note", "single-resource-note", "multi-document-note",
            "batch-resource-note", "note-reorganization",
        ),
        budget=LoopBudget(max_iterations=28, max_tool_calls=20, max_repeated_actions=2),
        required_artifact_types=("learning_note_bundle",),
        complete_on_task_ready=True,
    )

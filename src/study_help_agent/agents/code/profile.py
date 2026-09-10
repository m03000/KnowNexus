"""声明本地代码分析 Agent 的能力边界。"""

from study_help_agent.agents.registry import AgentProfile
from study_help_agent.runtime.budgets import LoopBudget


def create_code_profile() -> AgentProfile:
    """创建只操作高层分析用例的 Code Profile。"""

    return AgentProfile(
        key="code",
        name="Code Intelligence Sub-Agent",
        description="分析本地 Python 项目或单文件，生成代码块解释和项目报告。",
        system_instructions=(
            "你是本地 Python 代码理解专家。先区分用户要分析整个项目还是单个文件。"
            "项目任务调用 analyze_local_code_project，单文件任务调用 "
            "analyze_local_code_file，明确指定多个文件时调用 analyze_local_code_files；"
            "扫描、AST、范围规划、代码块解释和验收已经由内部条件图负责，不要尝试自行重建这些步骤。"
            "结果由底层默认保存，分析工具返回的 project_summary、file_summaries 和覆盖信息足够生成最终回答；"
            "项目工具返回 completed 后直接 finish，不要读取 Artifact。"
            "若 analyze_local_code_project 返回 partial 且 requires_followup=true，"
            "必须使用返回的 Artifact ID 调用 complete_code_analysis 一次；"
            "补齐工具返回后不得再调用任何代码分析工具。"
            "若补齐后仍非 completed，必须明确说明覆盖率和 failed_paths，不得把降级结果描述为完整分析。"
            "历史查询和删除由前端 API 负责。所有分析输入都必须来自允许访问的本地项目。"
        ),
        tool_names=(
            "analyze_local_code_project",
            "analyze_local_code_files",
            "analyze_local_code_file",
            "complete_code_analysis",
        ),
        # 三个高层工具内部已经封装范围规划、并行解释、增量补齐和验收，
        # Code Agent 只负责模式选择，不再加载重复流程 Skill。
        skill_names=(),
        budget=LoopBudget(max_iterations=6, max_tool_calls=3, max_repeated_actions=1),
        required_artifact_types=("code_analysis_project",),
        minimum_successful_actions=0,
    )

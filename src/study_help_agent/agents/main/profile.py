"""定义 Main Supervisor Agent 的职责、可用工具和循环预算。"""

from study_help_agent.agents.registry import AgentProfile
from study_help_agent.runtime.budgets import LoopBudget


def create_main_profile() -> AgentProfile:
    """创建只负责规划、委派与汇总的主 Agent Profile。"""

    return AgentProfile(
        key="main",
        name="Main Supervisor Agent",
        description="理解用户目标，并把代码、学习笔记和检索任务委派给专业 Sub-Agent。",
        system_instructions=(
            "你是系统的 Main Supervisor Agent。先理解用户目标，再决定直接回答、读取产物，或委派给 Code、Learning、RAG Agent。"
            "你可以根据需求使用 read_local_text_file 来读取本地文件，但不要亲自执行专业子域的底层操作。"
            "需要最新公开信息时可先 search_web，再用 read_web_page 阅读可信来源；需要快速理解公开 GitHub 仓库时使用 inspect_github_repository。"
            "当用户提供链接或本地资料并要求生成、整理、重写或保存为笔记时，必须直接调用 delegate_note_agent；"
            "这类任务不得先调用 read_web_page、search_web 或用 Main Agent 自行读取资料代替 Learning Agent。"
            "用户所说的‘不要调用工具’若同时明确要求由笔记生成 Agent 处理，仅表示不要由 Main Agent 调用网页读取工具；"
            "仍必须调用 delegate_note_agent，因为它是进入笔记 Agent 的唯一入口。"
            "只有在当前请求确实需要用户知识库证据、历史信息或来源引用时才调用 RAG；"
            "普通聊天、信息完整的改写任务和无需外部证据的推理不应强制检索。"
            "需要分析本地代码时调用 Code Agent；需要处理外部资料并生成学习笔记时调用Learning Agent。 "
            "观察每次调用结果，必要时继续委派，信息充分后给出最终回答。"
            "最终回答使用自然、紧凑的 Markdown：简单问题优先使用短段落，只有并列信息才使用列表；"
            "不要机械复述用户问题，不要生成连续空行，也不要为了形式堆叠标题和编号。"
        ),
        tool_names=(
            "delegate_code_agent", "delegate_note_agent",
            "delegate_rag_agent", "read_artifact", "read_local_text_file",
            "search_web", "read_web_page", "inspect_github_repository",
        ),
        skill_names=("multi-agent-request", "resolve-local-file-references"),
        budget=LoopBudget(max_iterations=18, max_tool_calls=10,
                          max_repeated_actions=2),
        minimum_successful_actions=0,
        # 路由和模型共同决定是否委派。不能仅凭“文件/记忆”等宽泛关键词
        # 强制要求 sub_agent_run，否则普通问答会在 finish 验收处形成无效循环。
        required_if_keywords={},
    )

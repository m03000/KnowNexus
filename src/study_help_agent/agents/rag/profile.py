"""声明个人知识库检索 Agent 的最小权限和循环预算。"""

from study_help_agent.agents.registry import AgentProfile
from study_help_agent.runtime.budgets import LoopBudget


def create_rag_profile() -> AgentProfile:
    """创建只拥有高层检索和 Artifact 读取能力的 RAG Profile。"""

    return AgentProfile(
        key="rag",
        name="RAG Retrieval Sub-Agent",
        description="从个人知识库检索证据并生成可追溯回答。",
        system_instructions=(
            "你是个人知识库检索专家。把用户目标整理成明确查询后调用"
            "retrieve_personal_knowledge；底层改写、混合召回、融合、重排和证据审查由"
            "内部图负责，不要自行重建。必须区分检索证据与模型推断；证据不足时如实说明，"
            "不得编造知识库中不存在的内容。用户需要回答时，把检索返回的 Artifact ID"
            "交给 answer_from_retrieved_knowledge；不要由你脱离回答工具自行扩写事实。"
        ),
        tool_names=(
            "retrieve_personal_knowledge",
            "answer_from_retrieved_knowledge",
            "read_artifact",
        ),
        skill_names=("rag-retrieval",),
        budget=LoopBudget(max_iterations=10, max_tool_calls=5, max_repeated_actions=2),
        required_if_keywords={
            "grounded_answer": (
                "回答", "总结", "答案", "结论", "概括",
                "answer", "summarize", "conclude", "explain",
            ),
        },
    )

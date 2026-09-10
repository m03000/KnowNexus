"""RAG 工具目录，只向 Agent 暴露完整检索用例。"""

from study_help_agent.capabilities.rag import RetrievalMiniAgent
from study_help_agent.capabilities.rag.mini_agents import GroundedAnswerMiniAgent
from study_help_agent.runtime.tools import ToolDefinition

from .retrieval import RAGRetrievalTools
from .answer import RAGAnswerTools


def create_rag_tool_groups(
    *, mini_agent: RetrievalMiniAgent, answer_mini_agent: GroundedAnswerMiniAgent
) -> tuple[tuple[ToolDefinition, ...], ...]:
    """注册一个高层检索工具，隐藏改写、召回、融合、重排和审查节点。"""

    return (
        RAGRetrievalTools(mini_agent=mini_agent).definitions(),
        RAGAnswerTools(mini_agent=answer_mini_agent).definitions(),
    )

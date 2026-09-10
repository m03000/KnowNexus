"""聚合项目默认 Agent Profile。"""

from study_help_agent.agents.code import create_code_profile
from study_help_agent.agents.note import create_note_profile
from study_help_agent.agents.main import create_main_profile
from study_help_agent.agents.rag import create_rag_profile
from study_help_agent.agents.registry import AgentProfileRegistry


def create_default_profiles() -> AgentProfileRegistry:
    """创建并注册主 Agent 与代码、学习、RAG 三个专业小 Agent。"""

    profiles = AgentProfileRegistry()
    profiles.register_many((
        create_main_profile(),
        create_code_profile(),
        create_note_profile(),
        create_rag_profile(),
    ))
    return profiles

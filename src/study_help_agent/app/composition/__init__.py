"""按领域拆分的应用依赖组合模块。

这些模块只能在应用启动阶段被调用，负责把具体基础设施连接到应用服务和 Tool Provider。
业务模块不得反向导入本包。
"""

from .code_analysis import CodeAnalysisComposition, compose_code_analysis
from .note import NoteComposition, compose_note
from .long_term_memory import LongTermMemoryComposition, compose_long_term_memory
from .rag import RAGComposition, compose_rag
from .knowledge_graph import compose_knowledge_graph
from .knowledge_ingestion import (
    KnowledgeIngestionComposition,
    compose_knowledge_ingestion,
)
from .runtime import compose_runtime_tool_groups
from .conversation_context import ConversationContextComposition, compose_conversation_context
from .external_conversation import compose_external_conversation

__all__ = [
    "CodeAnalysisComposition",
    "NoteComposition",
    "LongTermMemoryComposition",
    "RAGComposition",
    "KnowledgeIngestionComposition",
    "compose_code_analysis",
    "compose_note",
    "compose_long_term_memory",
    "compose_rag",
    "compose_knowledge_ingestion",
    "compose_runtime_tool_groups",
    "compose_knowledge_graph",
    "ConversationContextComposition",
    "compose_conversation_context",
    "compose_external_conversation",
]

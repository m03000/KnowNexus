"""图谱域的依赖组合模块。"""
from __future__ import annotations
from study_help_agent.capabilities.knowledge_graph.application.graph_service import (
    GraphQueryService,
)
from study_help_agent.capabilities.learning_notes.application.service import (
    LearningNoteService,
)
from study_help_agent.capabilities.code_analysis.application.service import (
    CodeAnalysisService,
)
from study_help_agent.capabilities.knowledge_graph.projections.project_graph import (
    build_project_graph,
    build_project_graph_children,
)
from study_help_agent.capabilities.knowledge_graph.projections.memory_graph import MemoryGraphAdapter
from study_help_agent.capabilities.long_term_memory.memory_store import MemoryStore
from study_help_agent.capabilities.llm_wiki.infrastructure import SqliteWikiRepository
from study_help_agent.infrastructure.persistence import SqliteConnectionFactory


def compose_knowledge_graph(
    *,
    note_service: LearningNoteService,
    code_service: CodeAnalysisService,
    memory_store: MemoryStore,
    conversation_repository,
    database: SqliteConnectionFactory,
    vector_store=None,
) -> GraphQueryService:
    """组装统一图谱查询服务（笔记/记忆/项目三域）。"""

    memory_graph = MemoryGraphAdapter(
        conversation_repository=conversation_repository,
        memory_store=memory_store,
        vector_store=vector_store,
    )
    wiki_repository = SqliteWikiRepository(database)

    def note_and_wiki_graph() -> dict:
        note_graph = note_service.graph_data()
        wiki_graph = wiki_repository.graph_data()
        source_page_by_node = {
            str(node.get("payload", {}).get("source_node_id")): str(node["id"])
            for node in wiki_graph.get("nodes", [])
            if node.get("payload", {}).get("source_node_id")
        }
        note_nodes = [
            node for node in note_graph.get("nodes", [])
            if str(node.get("id")) not in source_page_by_node
        ]
        note_edges = []
        for edge in note_graph.get("edges", []):
            normalized = dict(edge)
            normalized["source"] = source_page_by_node.get(str(edge.get("source")), edge.get("source"))
            normalized["target"] = source_page_by_node.get(str(edge.get("target")), edge.get("target"))
            if normalized["source"] != normalized["target"]:
                note_edges.append(normalized)
        wiki_edges = [
            edge for edge in wiki_graph.get("edges", [])
            if str(edge.get("target")) not in source_page_by_node
        ]
        return {
            "nodes": [*note_nodes, *wiki_graph.get("nodes", [])],
            "edges": [*note_edges, *wiki_edges],
        }

    return GraphQueryService(
        note_graph_provider=note_and_wiki_graph,
        memory_graph_provider=memory_graph.graph_data,
        memory_trace_provider=memory_graph.trace,
        memory_candidates_provider=memory_graph.semantic_candidates,
        memory_turn_provider=memory_graph.turn_detail,
        memory_session_rename_provider=lambda session_id, title: conversation_repository.rename_session(
            session_id, title=title,
        ),
        memory_session_delete_provider=conversation_repository.delete_session_with_memories,
        memory_turn_delete_provider=conversation_repository.delete_turn_with_memories,
        project_graph_provider=lambda project_id, include_blocks: build_project_graph(
            code_service, project_id=project_id, include_blocks=include_blocks,
        ),
        project_children_provider=lambda project_id, node_id: build_project_graph_children(
            code_service, project_id=project_id, node_id=node_id,
        ),
    )

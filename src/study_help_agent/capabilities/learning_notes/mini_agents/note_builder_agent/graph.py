"""构建审查、动态规划、多笔记生成和一次修订的 LearningNoteBuilderGraph。"""

from langgraph.graph import END, START, StateGraph

from .state import LearningNoteBuilderState


def build_learning_note_builder_graph(nodes):
    """编译完整笔记规划图；终止上限由代码控制，不交给模型自由循环。"""

    graph = StateGraph(LearningNoteBuilderState)
    graph.add_node("prepare", nodes.prepare)
    graph.add_node("audit_content", nodes.audit_content)
    graph.add_node("plan_small_note", nodes.plan_small_note)
    graph.add_node("plan_notes", nodes.plan_notes)
    graph.add_node("generate_notes", nodes.generate_notes)
    graph.add_node("review_notes", nodes.review_notes)
    graph.add_node("repair_notes", nodes.repair_notes)
    graph.add_node("finalize", nodes.finalize)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "audit_content")
    graph.add_conditional_edges(
        "audit_content",
        nodes.route_after_audit,
        {"small": "plan_small_note", "planned": "plan_notes"},
    )
    graph.add_edge("plan_small_note", "generate_notes")
    graph.add_edge("plan_notes", "generate_notes")
    graph.add_edge("generate_notes", "review_notes")
    graph.add_conditional_edges(
        "review_notes",
        nodes.route_after_review,
        {"revise": "repair_notes", "finish": "finalize"},
    )
    graph.add_edge("repair_notes", "review_notes")
    graph.add_edge("finalize", END)
    return graph.compile()

"""构建生成、引用校验、独立审查和一次有界修订的 GroundedAnswerGraph。"""

from langgraph.graph import END, START, StateGraph

from .state import GroundedAnswerState


def build_grounded_answer_graph(nodes):
    """编译回答质量闭环；终止由代码上限控制，不交给模型自由决定。"""

    graph = StateGraph(GroundedAnswerState)
    graph.add_node("prepare_evidence", nodes.prepare_evidence)
    graph.add_node("generate_answer", nodes.generate_answer)
    graph.add_node("validate_citations", nodes.validate_citations)
    graph.add_node("review_answer", nodes.review_answer)
    graph.add_node("prepare_revision", nodes.prepare_revision)
    graph.add_node("finalize", nodes.finalize)
    graph.add_edge(START, "prepare_evidence")
    graph.add_edge("prepare_evidence", "generate_answer")
    graph.add_edge("generate_answer", "validate_citations")
    graph.add_edge("validate_citations", "review_answer")
    graph.add_conditional_edges(
        "review_answer",
        nodes.route_after_review,
        {"revise": "prepare_revision", "finish": "finalize"},
    )
    graph.add_edge("prepare_revision", "generate_answer")
    graph.add_edge("finalize", END)
    return graph.compile()

"""构建带并行召回、证据审查与一次有界重试的基础 Retrieval Graph。"""

from langgraph.graph import END, START, StateGraph

from .state import RetrievalState


def build_retrieval_graph(nodes):
    """固定可靠检索主干，把查询改写和审查保留为语义节点。"""

    graph = StateGraph(RetrievalState)
    graph.add_node("prepare_query", nodes.prepare_query)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("route_spaces", nodes.route_spaces)
    graph.add_node("dispatch_retrieval", nodes.dispatch_retrieval)
    graph.add_node("retrieve_lexical", nodes.retrieve_lexical)
    graph.add_node("retrieve_vector", nodes.retrieve_vector)
    graph.add_node("retrieve_graph", nodes.retrieve_graph)
    graph.add_node("fuse_results", nodes.fuse_results)
    graph.add_node("rerank_results", nodes.rerank_results)
    graph.add_node("review_results", nodes.review_results)
    graph.add_node("prepare_retry", nodes.prepare_retry)
    graph.add_node("finalize", nodes.finalize)

    graph.add_edge(START, "prepare_query")
    graph.add_conditional_edges(
        "prepare_query",
        nodes.route_initial_query,
        {"rewrite": "rewrite_query", "retrieve": "route_spaces"},
    )
    graph.add_edge("rewrite_query", "route_spaces")
    graph.add_edge("route_spaces", "dispatch_retrieval")
    graph.add_edge("dispatch_retrieval", "retrieve_lexical")
    graph.add_edge("dispatch_retrieval", "retrieve_vector")
    graph.add_edge("dispatch_retrieval", "retrieve_graph")
    graph.add_edge("retrieve_graph", "fuse_results")
    graph.add_edge("retrieve_lexical", "fuse_results")
    graph.add_edge("retrieve_vector", "fuse_results")
    graph.add_edge("fuse_results", "rerank_results")
    graph.add_edge("rerank_results", "review_results")
    graph.add_conditional_edges(
        "review_results",
        nodes.route_after_review,
        {"retry": "prepare_retry", "finish": "finalize"},
    )
    graph.add_edge("prepare_retry", "dispatch_retrieval")
    graph.add_edge("finalize", END)
    return graph.compile()

"""构建本地代码分析的条件图。

宏观依赖由图保证：先准备证据，再规划范围、分析职责、解释代码块并验收。文件失败
可以进入一次有界重试；单文件与项目模式的差异由节点状态处理，而不是复制两套流程。
"""

from langgraph.graph import END, START, StateGraph

from .state import CodeAnalysisState


def build_code_analysis_graph(nodes):
    """使用注入的节点实现构建并编译可复用代码分析图。"""

    graph = StateGraph(CodeAnalysisState)
    graph.add_node("inspect_and_prepare", nodes.inspect_and_prepare)
    graph.add_node("plan_scope", nodes.plan_scope)
    graph.add_node("analyze_file_roles", nodes.analyze_file_roles)
    graph.add_node("summarize_project", nodes.summarize_project)
    graph.add_node("explain_files", nodes.explain_files)
    graph.add_node("validate_result", nodes.validate_result)
    graph.add_node("prepare_retry", nodes.prepare_retry)
    graph.add_edge(START, "inspect_and_prepare")
    graph.add_edge("inspect_and_prepare", "plan_scope")
    graph.add_edge("plan_scope", "analyze_file_roles")
    graph.add_edge("analyze_file_roles", "summarize_project")
    graph.add_edge("summarize_project", "explain_files")
    graph.add_edge("explain_files", "validate_result")
    graph.add_conditional_edges(
        "validate_result",
        nodes.route_after_validation,
        {"retry": "prepare_retry", "finish": END},
    )
    graph.add_edge("prepare_retry", "analyze_file_roles")
    return graph.compile()

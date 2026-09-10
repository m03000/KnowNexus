"""MCP 长期记忆溯源工具，将蒸馏事实关联回原始外部/内部对话。"""


def trace_memory(container, *, memory_id: str) -> dict:
    """返回记忆点、支持它的原始消息及按会话聚类的时间线。"""

    return container.graph_query_service.trace_memory(memory_id.strip())

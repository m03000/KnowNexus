"""MCP 知识检索工具。

将现有 RAG Mini-Agent 的强类型结果转换为 JSON，不复制向量、关键词、
图检索、融合、重排和文档审查逻辑。
"""

from __future__ import annotations

from dataclasses import asdict


def search_personal_knowledge(
    container,
    *,
    query: str,
    history_context: str = "",
    top_k: int = 5,
    recall_k: int = 15,
) -> dict:
    """检索项目代码、个人笔记和长期记忆，并返回审查后的证据块。"""

    result = container.rag_retrieval_mini_agent.retrieve(
        query=query,
        history_context=history_context,
        top_k=max(1, min(top_k, 20)),
        recall_k=max(1, min(recall_k, 100)),
    )
    return asdict(result)

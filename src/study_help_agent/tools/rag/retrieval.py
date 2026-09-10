"""把完整 Retrieval Graph 适配成一个语义明确的 Agent 工具。"""

from typing import Any, Mapping

from study_help_agent.capabilities.rag import RetrievalMiniAgent
from study_help_agent.runtime.serialization import to_serializable
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult


class RAGRetrievalTools:
    """提供个人知识库混合检索，并把完整证据保存为 Artifact。"""

    def __init__(self, *, mini_agent: RetrievalMiniAgent) -> None:
        self._mini_agent = mini_agent

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                name="retrieve_personal_knowledge",
                description=(
                    "从个人知识库检索与问题直接相关的证据。内部会按需改写查询，并行执行FTS5 关键词与 Qdrant 向量召回，"
                    "经 RRF 融合、CrossEncoder 重排和 LLM 证据审查后返回带来源文档；证据不足时最多改写重试一次。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "需要检索的问题。"},
                        "history_context": {
                            "type": "string",
                            "description": "消解指代所需的简短对话上下文，默认空。",
                        },
                        "top_k": {
                            "type": "integer", "minimum": 1, "maximum": 20,
                            "description": "审查前最多精排文档数，默认 3。",
                        },
                        "recall_k": {
                            "type": "integer", "minimum": 1, "maximum": 100,
                            "description": "每路粗召回数量，默认 10且不得小于 top_k。",
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=self.retrieve,
            ),
        )

    def retrieve(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """运行检索图并把完整证据与元数据写入共享 Artifact Store。"""

        result = self._mini_agent.retrieve(
            query=str(arguments["query"]),
            history_context=str(arguments.get("history_context", "")),
            top_k=int(arguments.get("top_k", 3)),
            recall_k=int(arguments.get("recall_k", 10)),
        )
        artifact = context.artifact_store.put(
            artifact_type="retrieved_context",
            name=result.query.effective_text[:80],
            summary=f"检索完成：{len(result.chunks)} 个通过审查的证据块。",
            content=to_serializable(result),
        )
        return ToolResult(
            summary=artifact.summary,
            payload={
                "artifact_id": artifact.artifact_id,
                "status": result.status,
                "effective_query": result.query.effective_text,
                "rewritten": result.query.rewritten,
                "result_count": len(result.chunks),
                "target_spaces": list(result.query.target_spaces),
                "routing_reason": result.query.routing_reason,
                "sources": list(dict.fromkeys(
                    chunk.source_file for chunk in result.chunks if chunk.source_file
                )),
                "review_summary": result.review_summary,
            },
            artifact_ids=(artifact.artifact_id,),
            warnings=result.warnings,
            partial=result.status != "completed",
        )

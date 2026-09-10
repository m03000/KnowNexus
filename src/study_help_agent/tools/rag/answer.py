"""把 GroundedAnswerMiniAgent 适配为消费检索 Artifact 的 RAG Agent 工具。"""

from typing import Any, Mapping

from study_help_agent.capabilities.rag import GroundedAnswerMiniAgent
from study_help_agent.runtime.serialization import to_serializable
from study_help_agent.runtime.tools import ToolDefinition, ToolExecutionContext, ToolResult


class RAGAnswerTools:
    """基于已经通过检索审查的文档生成可追溯回答。"""

    def __init__(self, *, mini_agent: GroundedAnswerMiniAgent) -> None:
        self._mini_agent = mini_agent

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                name="answer_from_retrieved_knowledge",
                description=(
                    "根据 retrieve_personal_knowledge 产生的 retrieved_context Artifact 回答问题。"
                    "内部回答图会生成初稿、校验 Chunk 引用、审查忠实度和问题覆盖，失败时最多修订一次；证据不足时明确返回不足，不会重新检索。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "retrieved_context_artifact_id": {"type": "string"},
                    },
                    "required": ["question", "retrieved_context_artifact_id"],
                    "additionalProperties": False,
                },
                handler=self.answer,
            ),
        )

    def answer(
        self, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """读取检索 Artifact，生成回答并保存独立 grounded_answer Artifact。"""

        artifact_id = str(arguments["retrieved_context_artifact_id"])
        source = context.artifact_store.get(artifact_id)
        if source.artifact_type != "retrieved_context":
            raise TypeError("回答工具只接受 retrieved_context Artifact")
        if not isinstance(source.content, Mapping):
            raise TypeError("retrieved_context Artifact 内容必须是对象")
        chunks = source.content.get("chunks", [])
        if not isinstance(chunks, list):
            raise TypeError("retrieved_context.chunks 必须是列表")

        answer = self._mini_agent.generate(
            question=str(arguments["question"]), chunks=chunks
        )
        chunks_by_id = {
            str(chunk.get("chunk_id")): chunk
            for chunk in chunks
            if isinstance(chunk, Mapping) and chunk.get("chunk_id")
        }
        citations = [
            {
                "chunk_id": chunk_id,
                "source_file": str(chunks_by_id[chunk_id].get("source_file", "")),
                "section_title": str(
                    chunks_by_id[chunk_id].get("section_title", "")
                ),
            }
            for chunk_id in answer.citation_chunk_ids
            if chunk_id in chunks_by_id
        ]
        payload = {
            "answer": answer.answer,
            "citations": citations,
            "insufficient_evidence": answer.insufficient_evidence,
            "review_summary": answer.review_summary,
            "status": answer.status,
            "revision_count": answer.revision_count,
            "retrieved_context_artifact_id": artifact_id,
        }
        result_artifact = context.artifact_store.put(
            artifact_type="grounded_answer",
            name=str(arguments["question"]).strip()[:80],
            summary=(
                "已基于检索证据生成回答。"
                if not answer.insufficient_evidence
                else "检索证据不足，已生成受限回答。"
            ),
            content=to_serializable(payload),
        )
        return ToolResult(
            summary=result_artifact.summary,
            payload={**payload, "artifact_id": result_artifact.artifact_id},
            artifact_ids=(result_artifact.artifact_id,),
            warnings=answer.warnings,
            partial=answer.status != "completed",
        )

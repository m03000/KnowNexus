"""回答图节点：证据约束、生成、引用校验、忠实度审查和有限修订。"""

from typing import Any, Mapping

from study_help_agent.capabilities.rag.llm.grounded_answer import (
    GroundedAnswerOperations,
)

from .state import GroundedAnswerState


class GroundedAnswerGraphNodes:
    """实现回答图各阶段，LLM 不参与确定性引用白名单和终止上限。"""

    MAX_CHUNK_CHARACTERS = 6_000
    MAX_CONTEXT_CHARACTERS = 24_000
    MAX_REVISIONS = 1

    def __init__(self, *, operations: GroundedAnswerOperations) -> None:
        self._operations = operations

    def prepare_evidence(self, state: GroundedAnswerState) -> dict:
        """校验问题和文档，并构造有字符上限的稳定证据列表。"""

        question = state["question"].strip()
        if not question:
            raise ValueError("回答问题不能为空")
        if not state.get("input_chunks"):
            raise ValueError("没有可用于生成回答的检索证据")
        evidence: list[dict[str, Any]] = []
        used_characters = 0
        for chunk in state["input_chunks"]:
            if not isinstance(chunk, Mapping):
                continue
            chunk_id = str(chunk.get("chunk_id", "")).strip()
            text = str(chunk.get("text", "")).strip()
            if not chunk_id or not text or used_characters >= self.MAX_CONTEXT_CHARACTERS:
                continue
            remaining = self.MAX_CONTEXT_CHARACTERS - used_characters
            bounded = text[: min(self.MAX_CHUNK_CHARACTERS, remaining)]
            evidence.append(
                {
                    "chunk_id": chunk_id,
                    "source_file": str(chunk.get("source_file", "")),
                    "section_title": str(chunk.get("section_title", "")),
                    "text": bounded,
                }
            )
            used_characters += len(bounded)
        if not evidence:
            raise ValueError("检索 Artifact 中没有有效文档块")
        return {
            "question": question,
            "evidence": evidence,
            "revision_count": 0,
            "revision_feedback": [],
            "warnings": [],
        }

    def generate_answer(self, state: GroundedAnswerState) -> dict:
        """生成初稿，或根据上一轮校验/审查反馈修订。"""

        output = self._operations.generate(
            question=state["question"],
            evidence=state["evidence"],
            feedback=state.get("revision_feedback", []),
        )
        return {
            "answer": output.answer.strip(),
            "requested_citation_ids": output.citation_chunk_ids,
            "insufficient_evidence": output.insufficient_evidence,
        }

    @staticmethod
    def validate_citations(state: GroundedAnswerState) -> dict:
        """过滤模型虚构引用，并检查非拒答回答至少存在一个合法引用。"""

        allowed = {item["chunk_id"] for item in state["evidence"]}
        requested = list(dict.fromkeys(state.get("requested_citation_ids", [])))
        valid = [chunk_id for chunk_id in requested if chunk_id in allowed]
        invalid = [chunk_id for chunk_id in requested if chunk_id not in allowed]
        passed = bool(valid) or state.get("insufficient_evidence", False)
        warnings = list(state.get("warnings", []))
        if invalid:
            warnings.append(f"已移除不存在的引用：{', '.join(invalid)}")
        if not passed:
            warnings.append("回答未提供有效 Chunk 引用")
        return {
            "valid_citation_ids": valid,
            "invalid_citation_ids": invalid,
            "citation_validation_passed": passed,
            "warnings": list(dict.fromkeys(warnings)),
        }

    def review_answer(self, state: GroundedAnswerState) -> dict:
        """独立审查事实忠实度、问题覆盖度和引用完整性。"""

        try:
            review = self._operations.review(
                question=state["question"],
                answer=state["answer"],
                citation_chunk_ids=state.get("valid_citation_ids", []),
                evidence=state["evidence"],
                insufficient_evidence=state.get("insufficient_evidence", False),
            )
            passed = (
                review.grounded
                and review.answers_question
                and (
                    review.citations_complete
                    or state.get("insufficient_evidence", False)
                )
                and state.get("citation_validation_passed", False)
            )
            return {
                "review_passed": passed,
                "review_summary": review.summary,
                "review_issues": review.issues,
            }
        except Exception as error:
            return {
                "review_passed": False,
                "review_summary": "回答审查模型调用失败。",
                "review_issues": [str(error)],
                "warnings": [*state.get("warnings", []), f"回答审查失败：{error}"],
            }

    @classmethod
    def route_after_review(cls, state: GroundedAnswerState) -> str:
        if state.get("review_passed"):
            return "finish"
        if int(state.get("revision_count", 0)) < cls.MAX_REVISIONS:
            return "revise"
        return "finish"

    @staticmethod
    def prepare_revision(state: GroundedAnswerState) -> dict:
        """合并确定性引用问题与 LLM 反馈，明确指导唯一一次修订。"""

        feedback = list(state.get("review_issues", []))
        if state.get("invalid_citation_ids"):
            feedback.append("删除不存在的引用，只使用证据中的 chunk_id")
        if not state.get("citation_validation_passed"):
            feedback.append("为事实性回答补充至少一个有效 Chunk 引用")
        return {
            "revision_feedback": list(dict.fromkeys(feedback)),
            "revision_count": int(state.get("revision_count", 0)) + 1,
        }

    @staticmethod
    def finalize(state: GroundedAnswerState) -> dict:
        """把双重验收结果收敛为 completed/partial，并保留失败原因。"""

        warnings = list(state.get("warnings", []))
        if not state.get("review_passed"):
            warnings.extend(state.get("review_issues", []))
            warnings.append("回答在修订上限内未通过完整质量审查")
        if state.get("insufficient_evidence"):
            warnings.append("检索证据不足，仅返回受限回答")
        status = (
            "completed"
            if state.get("review_passed") and not state.get("insufficient_evidence")
            else "partial"
        )
        return {"status": status, "warnings": list(dict.fromkeys(warnings))}

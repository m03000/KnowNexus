"""GroundedAnswerGraph 使用的回答生成与忠实度审查 LLM 操作。"""

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field, field_validator

from study_help_agent.infrastructure.llm.local_structured_output import LocalStructuredOutput


class GroundedAnswerOutput(BaseModel):
    """模型生成的证据约束回答与所使用的 Chunk ID。"""

    answer: str = Field(min_length=1)
    citation_chunk_ids: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False

    @field_validator("citation_chunk_ids")
    @classmethod
    def unique_citations(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class GroundedAnswerReviewOutput(BaseModel):
    """回答忠实度、问题覆盖度和引用完整性的审查结果。"""

    grounded: bool = False
    answers_question: bool = False
    citations_complete: bool = False
    summary: str = ""
    issues: list[str] = Field(default_factory=list)


class GroundedAnswerOperations:
    """提供回答草拟/修订和独立审查，不负责图路由或引用白名单。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self._generator = LocalStructuredOutput(llm, GroundedAnswerOutput)
        self._reviewer = LocalStructuredOutput(llm, GroundedAnswerReviewOutput)

    def generate(
        self,
        *,
        question: str,
        evidence: list[dict[str, Any]],
        feedback: list[str] | None = None,
    ) -> GroundedAnswerOutput:
        """首次生成或根据明确审查反馈修订证据约束回答。"""

        feedback_text = json.dumps(feedback or [], ensure_ascii=False)
        return self._generator.invoke(
            "你是严格的个人知识库问答助手。只能使用下方证据回答，不得补充模型自己的"
            "知识。每个事实性结论都必须能由至少一个文档块支撑。citation_chunk_ids 只能"
            "填写证据中存在的 chunk_id；证据不足时明确说明缺少依据，并将 "
            "insufficient_evidence 设为 true。若提供审查反馈，必须修复反馈指出的问题。\n\n"
            f"用户问题：\n{question}\n\n审查反馈：\n{feedback_text}\n\n"
            f"检索证据：\n{json.dumps(evidence, ensure_ascii=False)}"
        )

    def review(
        self,
        *,
        question: str,
        answer: str,
        citation_chunk_ids: list[str],
        evidence: list[dict[str, Any]],
        insufficient_evidence: bool,
    ) -> GroundedAnswerReviewOutput:
        """独立判断回答是否忠实、回应问题且引用覆盖充分。"""

        return self._reviewer.invoke(
            "你是 RAG 回答质量审查器。逐项比较回答与证据，不得使用外部知识。grounded "
            "表示所有事实都能由证据支持；answers_question 表示回答直接回应问题，或在证据"
            "不足时正确说明不足；citations_complete 表示关键结论的引用充分。发现问题时"
            "issues 必须给出可以指导下一轮修订的具体反馈。\n\n"
            f"问题：\n{question}\n\n回答：\n{answer}\n\n"
            f"引用 Chunk：\n{json.dumps(citation_chunk_ids, ensure_ascii=False)}\n\n"
            f"回答声明证据不足：{insufficient_evidence}\n\n"
            f"证据：\n{json.dumps(evidence, ensure_ascii=False)}"
        )

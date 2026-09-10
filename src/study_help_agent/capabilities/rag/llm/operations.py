"""实现查询改写、文档检查。"""

import json

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.capabilities.rag.domain.models import RetrievedChunk
from study_help_agent.infrastructure.llm.local_structured_output import LocalStructuredOutput

from .schemas import QueryRewriteOutput, QueryRouteOutput, RetrievalReviewOutput


class RetrievalLLMOperations:
    """承担需要语义判断的查询改写和检索证据审查。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self._rewriter = LocalStructuredOutput(llm, QueryRewriteOutput)
        self._reviewer = LocalStructuredOutput(llm, RetrievalReviewOutput)
        self._router = LocalStructuredOutput(llm, QueryRouteOutput)

    def route(self, query: str) -> QueryRouteOutput:
        """根据问题语义选择最少且足够的知识空间。"""

        return self._router.invoke(
            "你是个人知识库检索路由器。只能从 project_code、personal_knowledge、"
            "user_memory 中选择。项目源码、函数、模块、代码实现问题选择 project_code；"
            "学习笔记、文档、视频整理内容选择 personal_knowledge；用户长期偏好、历史决定"
            "选择 user_memory。问题跨域时可选择多个，但不要无理由全选。\n\n"
            f"用户问题：\n{query}"
        )

    def rewrite(self, query: str, history_context: str = "") -> str:
        """消解指代、规范术语，但不得改变问题核心意图。"""

        result = self._rewriter.invoke(
            "你是查询改写助手。结合对话历史消解指代，将口语表达改为独立、明确、"
            "适合关键词与向量检索的查询。不要回答问题，不要添加用户没有表达的目标。\n\n"
            f"对话历史：\n{history_context or '无'}\n\n原始问题：\n{query}"
        )
        return result.query.strip()

    def review(
        self, query: str, chunks: list[RetrievedChunk]
    ) -> RetrievalReviewOutput:
        """逐块检查相关性，并判断保留证据是否足以支撑回答。"""

        candidates = [
            {
                "chunk_id": chunk.chunk_id,
                "source_file": chunk.source_file,
                "section_title": chunk.section_title,
                "text": chunk.text,
                "rerank_score": chunk.rerank_score,
            }
            for chunk in chunks
        ]
        return self._reviewer.invoke(
            "你是严格的 RAG 检索证据审查器。只保留直接回答或实质支撑查询的文档块。"
            "不得因为主题相近就保留；只能返回候选中存在的 chunk_id。sufficient 表示保留"
            "证据是否足以支持一个有依据的回答。若证据不足，issues 说明缺少什么。\n\n"
            f"查询：\n{query}\n\n候选文档：\n{json.dumps(candidates, ensure_ascii=False)}"
        )

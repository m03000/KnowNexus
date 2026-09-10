"""确定性查询改写策略。"""


class QueryRewritePolicy:
    """用长度、完整问句和指代词判断是否值得调用 LLM 改写。"""

    _complete_patterns = (
        "是什么", "什么是", "怎么实现", "如何实现", "有哪些", "怎样", "为什么", "的区别",
    )
    _domain_terms = (
        "ReAct", "Function Calling", "RAG", "Agent", "LLM", "BM25", "Reranker",
        "Embedding", "Chunk", "向量", "Prompt", "Tool", "记忆", "检索", "分块", "混合检索",
    )
    _vague_words = (
        "它", "他", "她", "这个", "那个", "这些", "那些", "上面", "前面", "刚才",
        "之前", "上一条", "上述",
    )

    def needs_rewrite(self, query: str, history_context: str = "") -> bool:
        """清晰的领域问题直查，短句或指代问题改写。"""

        normalized = query.strip()
        if len(normalized) >= 15:
            complete = any(pattern in normalized for pattern in self._complete_patterns)
            domain = any(term.lower() in normalized.lower() for term in self._domain_terms)
            if complete and domain:
                return False
        if self.has_vague_reference(normalized):
            return True
        if len(normalized) < 15:
            return True
        return False

    def has_vague_reference(self, query: str) -> bool:
        """判断查询是否包含需要结合历史消解的常见指代词。"""

        return any(word in query for word in self._vague_words)

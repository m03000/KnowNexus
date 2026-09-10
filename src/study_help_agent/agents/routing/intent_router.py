import re

from .models import RequestIntent, RouteDecision


class MainIntentRouter:
    """只识别高置信度请求，其余全部交给 Main Loop。"""

    CODE_WORDS = (
        "解析代码", "分析代码", "解析项目",
        "分析项目", "解析文件", "分析文件",
        "项目架构", "代码块", "调用链",
    )

    NOTE_WORDS = (
        "生成笔记", "整理笔记", "合并文档",
        "合并笔记", "视频生成笔记", "文档生成笔记",
    )

    RAG_WORDS = (
        "查询知识库", "检索笔记", "在我的知识库",
        "从项目知识中查找", "从记忆中检索",
    )

    PATH_PATTERN = re.compile(
        r"[A-Za-z]:[\\/][^\n]+"
    )
    VAGUE_REFERENCES = (
        "刚才", "之前", "上面", "那些", "这个项目", "这个文件", "前几个",
    )

    def route(self, message: str) -> RouteDecision:
        normalized = message.strip()

        if any(word in normalized for word in self.VAGUE_REFERENCES):
            return RouteDecision(
                intent=RequestIntent.COMPLEX,
                confidence=1.0,
                reason="请求包含需要短期记忆消歧的指代表达",
                requires_main_loop=True,
            )

        matched: list[RequestIntent] = []

        if any(word in normalized for word in self.CODE_WORDS):
            matched.append(RequestIntent.CODE)

        if any(word in normalized for word in self.NOTE_WORDS):
            matched.append(RequestIntent.NOTE)

        if any(word in normalized for word in self.RAG_WORDS):
            matched.append(RequestIntent.RAG)

        # 同时命中多个领域，应进入 Main Loop。
        if len(set(matched)) > 1:
            return RouteDecision(
                intent=RequestIntent.COMPLEX,
                confidence=1.0,
                reason="请求同时涉及多个专业领域",
                requires_main_loop=True,
            )

        if matched == [RequestIntent.CODE]:
            # 明确代码意图但没有路径，仍可能需要 Main 读取记忆。
            has_path = bool(self.PATH_PATTERN.search(normalized))

            return RouteDecision(
                intent=RequestIntent.CODE,
                confidence=0.95 if has_path else 0.65,
                reason="命中代码解析意图",
                profile_key="code",
                requires_main_loop=not has_path,
            )

        if matched == [RequestIntent.NOTE]:
            return RouteDecision(
                intent=RequestIntent.NOTE,
                confidence=0.9,
                reason="命中学习笔记意图",
                profile_key="note",
                requires_main_loop=False,
            )

        if matched == [RequestIntent.RAG]:
            return RouteDecision(
                intent=RequestIntent.RAG,
                confidence=0.9,
                reason="命中个人知识库检索意图",
                profile_key="rag",
                requires_main_loop=False,
            )

        return RouteDecision(
            intent=RequestIntent.COMPLEX,
            confidence=0.0,
            reason="无法通过确定性规则高置信度识别",
            requires_main_loop=True,
        )

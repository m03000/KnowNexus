"""短期会话摘要的 LLM 适配器。"""

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.infrastructure.llm.local_structured_output import LocalStructuredOutput
from .schemas import SessionSummaryOutput


class ConversationSummaryOperations:
    """将旧摘要和被压缩消息合并为新的滚动摘要。"""

    def __init__(self, llm: BaseChatModel) -> None:
        self._output = LocalStructuredOutput(llm, SessionSummaryOutput)

    def summarize(self, *, previous_summary: str, messages_text: str) -> str:
        prompt = f"""请将历史会话压缩成供 Agent 继续当前任务使用的会话摘要。

已有摘要：
{previous_summary or '无'}

新增历史消息：
{messages_text}

只保留当前目标、用户明确决定、已完成和待完成事项、重要技术上下文、
相关文件或产物以及未解决问题。删除寒暄、重复解释、工具日志和已失效结论。
不要提取跨会话用户画像；那是长期记忆的职责。
"""
        return self._output.invoke(prompt).summary.strip()

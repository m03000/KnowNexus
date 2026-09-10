"""仅负责把短期摘要、任务状态和近期消息组装成 Agent 上下文。"""

from study_help_agent.capabilities.conversation_context.application.ports import ConversationContextRepository


class SessionContextService:
    """短期上下文读取服务；不触发长期记忆检索或蒸馏。"""

    def __init__(self, *, repository: ConversationContextRepository,
                 recent_message_limit: int = 12,
                 max_characters: int = 24_000) -> None:
        self._repository = repository
        self._recent_message_limit = recent_message_limit
        self._max_characters = max_characters

    def build_goal(self, session_id: str, current_message: str) -> str:
        # 从sqlite里面查询短期记忆
        memory = self._repository.get_context_snapshot(
            session_id, recent_message_limit=self._recent_message_limit
        )
        # 1. 历史对话摘要
        sections: list[str] = []
        if memory.summary.strip():
            sections.extend(("【当前会话摘要】", memory.summary.strip()))
        # 2. 短期记忆中实现的任务执行状态
        task = memory.active_context
        if task.active_goal or task.completed_steps or task.pending_steps:
            sections.append("【当前任务状态】")
            if task.active_goal:
                sections.append(f"当前目标：{task.active_goal}")
            if task.completed_steps:
                sections.append("已完成：" + "；".join(task.completed_steps))
            if task.pending_steps:
                sections.append("待处理：" + "；".join(task.pending_steps))
        # 3. 最近几轮对话原文
        if memory.messages:
            sections.append("【近期对话】")
            sections.extend(f"{item.role}: {item.content}" for item in memory.messages)
        sections.extend(("【当前用户请求】", current_message.strip()))
        result = "\n".join(sections)
        if len(result) <= self._max_characters:
            return result
        # 始终保留当前请求和最靠近现在的上下文。
        return result[-self._max_characters:]

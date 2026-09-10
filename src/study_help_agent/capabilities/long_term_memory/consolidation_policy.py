"""长期记忆批量蒸馏的纯策略，不执行数据库或 LLM 操作。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConsolidationDecision:
    should_consolidate: bool
    reason: str


class MemoryConsolidationPolicy:
    """按轮数、体量和显式记忆事件决定何时调用昂贵的 LLM。"""

    _immediate_keywords = (
        "记住", "请记住", "以后都", "以后不要", "我决定", "我确定",
        "我的偏好", "不要再记", "忘记这件事", "取消之前",
    )

    def __init__(self, *, max_pending_turns: int = 3,
                 max_pending_characters: int = 8000) -> None:
        self._max_pending_turns = max_pending_turns
        self._max_pending_characters = max_pending_characters

    def decide(self, *, pending_messages, force: bool = False) -> ConsolidationDecision:
        if not pending_messages:
            return ConsolidationDecision(False, "没有待蒸馏消息")
        if force:
            return ConsolidationDecision(True, "外部强制刷新")
        user_messages = [item for item in pending_messages if item.role == "user"]
        if any(keyword in item.content for item in user_messages
               for keyword in self._immediate_keywords):
            return ConsolidationDecision(True, "检测到显式记忆事件")
        if len(user_messages) >= self._max_pending_turns:
            return ConsolidationDecision(True, "累计达到蒸馏轮数")
        if sum(len(item.content) for item in pending_messages) >= self._max_pending_characters:
            return ConsolidationDecision(True, "待处理内容超过字符预算")
        return ConsolidationDecision(False, "继续累积待处理消息")

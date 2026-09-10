"""短期上下文长度预算。"""


class ContextBudget:
    def __init__(
        self,
        *,
        max_messages: int = 12,
        max_characters: int = 24_000,
        compaction_trigger_characters: int = 18_000,
    ) -> None:
        self.max_messages = max_messages
        self.max_characters = max_characters
        self.compaction_trigger_characters = (
            compaction_trigger_characters
        )

    def requires_compaction(
        self,
        messages,
    ) -> bool:
        if len(messages) > self.max_messages:
            return True

        total = sum(
            len(message.content)
            for message in messages
        )

        return total > self.compaction_trigger_characters

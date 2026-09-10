"""外部对话 Capability 的组合根，将仓储和长期记忆服务连接起来。"""

from study_help_agent.capabilities.external_conversation import (
    ExternalConversationCaptureService,
)


def compose_external_conversation(*, repository, memory_consolidator, turn_indexer):
    """创建进程级外部对话捕获服务，不重新创建数据库或蒸馏器。"""

    return ExternalConversationCaptureService(
        repository=repository,
        memory_consolidator=memory_consolidator,
        turn_indexer=turn_indexer,
    )

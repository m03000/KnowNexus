"""把原始对话轮次可靠投递到 USER_MEMORY 的 FTS5/Qdrant 检索索引。

SQLite 是原始对话和蒸馏记忆点的事实主库；搜索后端只保存原始对话轮次的
检索投影。蒸馏记忆点由 SQLite FTS5、结构化字段和记忆关系图查询。
"""

from __future__ import annotations

from typing import Protocol

from study_help_agent.capabilities.conversation_context.domain.models import SessionMessage
from study_help_agent.capabilities.knowledge_ingestion.domain.enums import (
    KnowledgeAssetType,
    KnowledgeSpace,
)
from study_help_agent.capabilities.knowledge_ingestion.domain.models import KnowledgeAssetDraft


class MemoryIndexRepository(Protocol):
    def upsert_and_enqueue(self, draft: KnowledgeAssetDraft): ...
    def request_delete_by_source_key(self, stable_source_key: str) -> int: ...
    def request_delete_by_source_prefix(self, source_prefix: str) -> int: ...


class MemorySearchIndexer:
    """原始对话检索投影器；保留类名以兼容现有组合根。"""

    def __init__(self, *, repository: MemoryIndexRepository) -> None:
        self._repository = repository

    def upsert_turn(
        self,
        *,
        session_id: str,
        user: SessionMessage,
        assistant: SessionMessage,
        title: str = "",
    ) -> None:
        """将一个完整问答合并成一个可检索 Conversation Episode。"""

        if not user.content.strip() or not assistant.content.strip():
            return
        self._repository.upsert_and_enqueue(
            KnowledgeAssetDraft(
                space=KnowledgeSpace.USER_MEMORY,
                asset_type=KnowledgeAssetType.CONVERSATION_EPISODE,
                stable_source_key=self._source_key(
                    session_id, user.message_id, assistant.message_id
                ),
                title=title.strip() or user.content.strip()[:48],
                content=(
                    f"用户：{user.content.strip()}\n\n"
                    f"助手：{assistant.content.strip()}"
                ),
                metadata={
                    "session_id": session_id,
                    "user_message_id": user.message_id,
                    "assistant_message_id": assistant.message_id,
                    "message_ids": [user.message_id, assistant.message_id],
                    "origin_type": user.origin_type,
                    "origin_client": user.origin_client,
                },
            )
        )

    def delete_turn(
        self, *, session_id: str, user_message_id: int, assistant_message_id: int,
    ) -> None:
        self._repository.request_delete_by_source_key(
            self._source_key(session_id, user_message_id, assistant_message_id)
        )

    def retire_legacy_memory_point_indexes(self) -> int:
        """清理旧版本写入搜索后端的 memory:<id> 资产。"""

        return self._repository.request_delete_by_source_prefix("memory:")

    @staticmethod
    def _source_key(
        session_id: str, user_message_id: int, assistant_message_id: int,
    ) -> str:
        return f"conversation:{session_id}:{user_message_id}:{assistant_message_id}"

"""短期记忆门面：统一提供上下文读取、原始轮次保存和滚动压缩。"""

import logging

from .compaction_service import SessionCompactionService
from .context_service import SessionContextService
from .ports import ConversationContextRepository
from ..domain.models import ActiveTaskContext, SavedTurn
from ..domain.models import SessionMessage

logger = logging.getLogger(__name__)


class ConversationContextService:
    """短期记忆的应用入口；不调用长期记忆服务。"""

    def __init__(self, *, repository: ConversationContextRepository,
                 context_service: SessionContextService,
                 compaction_service: SessionCompactionService,
                 turn_indexer=None) -> None:
        self._repository = repository
        self._context_service = context_service
        self._compaction_service = compaction_service
        self._turn_indexer = turn_indexer

    def set_turn_indexer(self, turn_indexer) -> None:
        """在组合根装配原始对话检索投影器，保持短期记忆与 RAG 领域解耦。"""

        self._turn_indexer = turn_indexer

    def build_goal(self, session_id: str, current_message: str) -> str:
        return self._context_service.build_goal(session_id, current_message)

    def get_recorded_turn(self, session_id: str, *,
                          turn_id: str) -> tuple[str, str] | None:
        """按幂等键读取已完成轮次，供 API 重试直接复用原回答。"""

        return self._repository.get_recorded_turn(session_id, turn_id=turn_id)

    def record_turn(self, session_id: str, *, user_message: str,
                    assistant_message: str, turn_id: str) -> SavedTurn:
        """记录一轮短期记忆"""
        saved = self._repository.save_turn(
            session_id, turn_id=turn_id, user_message=user_message,
            assistant_message=assistant_message
        )
        self._index_saved_turn(
            saved=saved,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        try:
            self._compaction_service.compact_if_needed(session_id)
        except Exception:
            # 摘要失败不能让已经完成的 Agent 回复失败；下轮仍可重试。
            logger.warning("短期记忆压缩失败", exc_info=True)
        return saved

    def _index_saved_turn(
        self, *, saved: SavedTurn, user_message: str, assistant_message: str,
    ) -> None:
        """把已提交的完整问答投影到 RAG；失败只记录，蒸馏时会幂等补偿。"""

        if self._turn_indexer is None:
            return
        try:
            now = ""
            self._turn_indexer.upsert_turn(
                session_id=saved.session_id,
                user=SessionMessage(
                    message_id=saved.user_message_id,
                    role="user", content=user_message, created_at=now,
                ),
                assistant=SessionMessage(
                    message_id=saved.assistant_message_id,
                    role="assistant", content=assistant_message, created_at=now,
                ),
                title=user_message[:48],
            )
        except Exception:
            logger.warning("原始对话 RAG 投影失败，等待长期蒸馏补偿", exc_info=True)

    def update_active_context(self, session_id: str,
                              context: ActiveTaskContext) -> None:
        self._repository.update_active_context(session_id, context)

    def list_sessions(self, *, limit: int = 50) -> tuple[dict, ...]:
        """列出网页内部会话，供对话主页侧栏展示。"""

        return self._repository.list_internal_sessions(limit=limit)

    def get_messages(self, session_id: str) -> tuple[dict, ...]:
        """返回一个内部会话的原始消息历史。"""

        return tuple({
            "message_id": item.message_id,
            "role": item.role,
            "content": item.content,
            "created_at": item.created_at,
        } for item in self._repository.list_session_messages(session_id))

    def delete_session(self, session_id: str) -> bool:
        """删除内部短期会话；已经蒸馏的长期记忆保持独立。"""

        return self._repository.delete_internal_session(session_id)
    def create_session(self, session_id: str, *, title: str = "新对话") -> dict:
        """在首轮消息执行前持久化空会话，使刷新不会丢失新对话。"""

        normalized_id = session_id.strip()
        if not normalized_id:
            raise ValueError("session_id 不能为空")
        return self._repository.create_internal_session(
            normalized_id,
            title=title.strip() or "新对话",
        )

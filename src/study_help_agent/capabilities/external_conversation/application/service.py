"""外部对话捕获应用服务。

服务把外部平台 ID 转换为本系统稳定 ID，原子保存完整轮次，再按既有策略触发
长期记忆蒸馏，不调用短期记忆压缩，外部智能体自己维护当前上下文。
"""

from __future__ import annotations

import hashlib
import logging

from study_help_agent.capabilities.conversation_context.domain.models import SessionMessage

from study_help_agent.capabilities.external_conversation.domain import (
    CaptureResult,
    ExternalConversationTurn,
)

logger = logging.getLogger(__name__)


def _stable_id(prefix: str, *parts: str) -> str:
    """把外部 ID 命名空间化，避免不同客户端或会话发生主键冲突。"""

    payload = "\x1f".join(part.strip() for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


class ExternalConversationCaptureService:
    """统一接收 Codex、WorkBuddy 或手动 MCP 上报的已完成轮次。"""

    def __init__(self, *, repository, memory_consolidator, turn_indexer=None) -> None:
        self._repository = repository
        self._memory_consolidator = memory_consolidator
        self._turn_indexer = turn_indexer

    def capture_turn(
        self,
        turn: ExternalConversationTurn,
        *,
        force_consolidation: bool = False,
        defer_consolidation: bool = False,
    ) -> CaptureResult:
        """幂等保存一轮外部对话，并让长期记忆按批次策略决定是否蒸馏。"""
        # 校验外部轮次并规范化客户端信息名称
        normalized = self._validate(turn)
        session_id = _stable_id(
            "external-session", normalized.client, normalized.external_session_id
        )
        # 生成稳定内部id
        turn_id = _stable_id(
            "external-turn",
            normalized.client,
            normalized.external_session_id,
            normalized.external_turn_id,
        )
        # 保存请求并判断请求是否重复
        existing = self._repository.get_recorded_turn(session_id, turn_id=turn_id)
        if existing is not None:
            saved = self._repository.get_saved_turn(session_id, turn_id=turn_id)
            return CaptureResult(
                session_id=session_id,
                turn_id=turn_id,
                duplicate=True,
                user_message_id=saved.user_message_id,
                assistant_message_id=saved.assistant_message_id,
                consolidation={
                    "consolidated": False,
                    "reason": "deferred" if defer_consolidation else "duplicate",
                },
            )
        # 保存完整轮次内容
        saved = self._repository.save_turn(
            session_id,
            turn_id=turn_id,
            user_message=normalized.user_message,
            assistant_message=normalized.assistant_message,
            origin_type="external",
            origin_client=normalized.client,
            external_session_id=normalized.external_session_id,
            external_turn_id=normalized.external_turn_id,
            title=normalized.title,
            metadata={
                **normalized.metadata,
                "cwd": normalized.cwd,
                "model": normalized.model,
                "transcript_path": normalized.transcript_path,
            },
        )
        self._index_saved_turn(
            session_id=session_id,
            saved=saved,
            turn=normalized,
        )
        # defer_consolidation=True 用于 HTTP 自动捕获，表示：先保存并交给后台任务
        if defer_consolidation:
            return CaptureResult(
                session_id=session_id,
                turn_id=turn_id,
                duplicate=False,
                user_message_id=saved.user_message_id,
                assistant_message_id=saved.assistant_message_id,
                consolidation={"consolidated": False, "reason": "deferred"},
            )
        try:
            # 满足蒸馏条件进行蒸馏
            consolidation = self._memory_consolidator.consolidate_if_needed(
                session_id=session_id,
                force=force_consolidation,
            )
        except Exception:
            # 原文已经安全落库；蒸馏失败可由下次轮次或显式 flush 重试。
            logger.warning("外部对话长期记忆蒸馏失败", exc_info=True)
            consolidation = {"consolidated": False, "reason": "consolidation_failed"}
        return CaptureResult(
            session_id=session_id,
            turn_id=turn_id,
            duplicate=False,
            user_message_id=saved.user_message_id,
            assistant_message_id=saved.assistant_message_id,
            consolidation=consolidation,
        )

    def _index_saved_turn(self, *, session_id: str, saved, turn) -> None:
        """即时索引外部完整问答；失败不回滚 SQLite 原文。"""

        if self._turn_indexer is None:
            return
        try:
            self._turn_indexer.upsert_turn(
                session_id=session_id,
                user=SessionMessage(
                    message_id=saved.user_message_id,
                    role="user", content=turn.user_message, created_at="",
                    origin_type="external", origin_client=turn.client,
                ),
                assistant=SessionMessage(
                    message_id=saved.assistant_message_id,
                    role="assistant", content=turn.assistant_message, created_at="",
                    origin_type="external", origin_client=turn.client,
                ),
                title=turn.title,
            )
        except Exception:
            logger.warning("外部原始对话 RAG 投影失败，等待蒸馏补偿", exc_info=True)

    def consolidate_session_id(self, *, session_id: str, force: bool = False) -> dict:
        """供 HTTP 后台任务调用；原文响应与耗时 LLM 蒸馏解耦。"""

        return self._memory_consolidator.consolidate_if_needed(
            session_id=session_id,
            force=force,
        )

    def capture_many(
        self,
        turns: list[ExternalConversationTurn],
        *,
        force_last_consolidation: bool = False,
    ) -> tuple[CaptureResult, ...]:
        """顺序导入一批轮次；仅最后一轮可强制刷新，避免每轮都调用 LLM。"""

        results: list[CaptureResult] = []
        for index, turn in enumerate(turns):
            results.append(
                self.capture_turn(
                    turn,
                    force_consolidation=(
                        force_last_consolidation and index == len(turns) - 1
                    ),
                )
            )
        return tuple(results)

    def flush_session(self, *, client: str, external_session_id: str) -> dict:
        """在 SessionEnd 或显式命令中强制处理尚未蒸馏的原始消息。"""

        session_id = _stable_id("external-session", client, external_session_id)
        return self._memory_consolidator.consolidate_if_needed(
            session_id=session_id,
            force=True,
        )

    @staticmethod
    def _validate(turn: ExternalConversationTurn) -> ExternalConversationTurn:
        client = turn.client.strip().casefold()
        if not client or not turn.external_session_id.strip() or not turn.external_turn_id.strip():
            raise ValueError("client、external_session_id 和 external_turn_id 不能为空")
        if not turn.user_message.strip() or not turn.assistant_message.strip():
            raise ValueError("外部对话必须同时包含用户输入和最终助手回复")
        return ExternalConversationTurn(
            client=client,
            external_session_id=turn.external_session_id.strip(),
            external_turn_id=turn.external_turn_id.strip(),
            user_message=turn.user_message.strip(),
            assistant_message=turn.assistant_message.strip(),
            title=turn.title.strip(),
            cwd=turn.cwd.strip(),
            model=turn.model.strip(),
            transcript_path=turn.transcript_path.strip(),
            metadata=dict(turn.metadata),
        )

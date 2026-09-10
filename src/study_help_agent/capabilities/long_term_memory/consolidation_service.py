"""协调待处理消息、触发策略、旧记忆召回和蒸馏游标。"""

from uuid import uuid4


class MemoryConsolidationService:
    def __init__(
        self,
        *,
        repository,
        policy,
        distiller,
        related_memories,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._distiller = distiller
        self._related_memories = related_memories

    def consolidate_if_needed(
        self,
        *,
        session_id: str,
        force: bool = False,
    ) -> dict:
        owner_id = uuid4().hex
        if not self._repository.acquire_lease(
            session_id, purpose="long_consolidation", owner_id=owner_id
        ):
            return {
                "consolidated": False,
                "reason": "同一会话已有长期记忆任务运行",
                "message_count": 0,
            }
        try:
            return self._consolidate(session_id=session_id, force=force)
        finally:
            self._repository.release_lease(
                session_id, purpose="long_consolidation", owner_id=owner_id
            )

    def _consolidate(self, *, session_id: str, force: bool) -> dict:
        """在取得跨进程租约后处理一个待蒸馏消息批次。"""
        pending = self._repository.pending_messages(
            session_id,
            # 每次最多蒸馏三轮。此前一次最多发送十轮，长回答很容易超过模型
            # 上下文或使结构化输出漏掉轮次，导致游标永久停在 0。
            limit=6,
        )

        decision = self._policy.decide(
            pending_messages=pending,
            force=force,
        )

        if not decision.should_consolidate:
            return {
                "consolidated": False,
                "reason": decision.reason,
                "message_count": len(pending),
            }

        query = "\n".join(
            message.content
            for message in pending
            if message.role == "user"
        )

        existing = self._related_memories.search(
            query,
            limit=5,
        )

        succeeded = self._distiller.distill_batch(
            session_id=session_id,
            messages=pending,
            existing_memories=existing,
        )

        if not succeeded:
            detail = str(getattr(self._distiller, "last_error", "") or "").strip()
            return {
                "consolidated": False,
                "reason": (
                    f"蒸馏执行失败：{detail}"
                    if detail else "蒸馏执行失败，保留游标等待重试"
                ),
                "message_count": len(pending),
            }

        last_message_id = pending[-1].message_id

        self._repository.update_distillation_cursor(
            session_id,
            message_id=last_message_id,
        )

        return {
            "consolidated": True,
            "reason": decision.reason,
            "message_count": len(pending),
            "distilled_until_message_id": (
                last_message_id
            ),
            **dict(getattr(self._distiller, "last_metrics", {}) or {}),
        }

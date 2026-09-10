"""把多轮原始消息蒸馏为可跨会话复用的长期记忆点。"""

import logging
from datetime import UTC, datetime
from hashlib import sha256

from langchain_core.language_models.chat_models import BaseChatModel

from study_help_agent.capabilities.conversation_context.domain.models import SessionMessage
from study_help_agent.infrastructure.llm.local_structured_output import LocalStructuredOutput
from .memory_search_indexer import MemorySearchIndexer
from .memory_store import MemoryPoint, MemoryRelation, MemoryStore
from .schemas import DistillationItem, DistillationOutput

logger = logging.getLogger(__name__)


def compute_memory_id(content: str, source_message_ids: list[int]) -> str:
    """按规范化事实生成稳定 ID；证据变化不再制造新的记忆实体。"""

    del source_message_ids
    canonical = " ".join(content.casefold().split())
    return sha256(canonical.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_DISTILL_PROMPT = """请批量处理下面的多个完整对话轮次，并为每个轮次独立提取长期记忆。

现有相关记忆：
{existing_memories}

待处理轮次：
{conversation_turns}

输出规则：
1. turns 必须按输入轮次分别输出，填写该轮的 user_message_id 和 assistant_message_id；
2. 优先提取记忆。用户的偏好、经历、稳定事实、学习内容、长期目标、明确决定，以及后续
   对话可能复用的项目背景，都应生成一个或多个原子记忆；
3. 只有纯寒暄、无信息确认、明显临时且不可复用的操作细节，才允许 items 为空；
4. 禁止把不同轮次概括成一条综合记忆。每个 item 的 source_message_ids 只能填写当前轮次
   的 user_message_id、assistant_message_id，通常两者都填写；
5. 一轮包含多个相互独立的信息时拆成多个 item，不要写成笼统的大段总结；
6. add 表示新增；update 必须给 target_memory_id；delete 仅用于用户明确取消旧记忆；
   noop 仅表示当前轮次确实没有可保存信息；
7. 不得把助手猜测当作用户事实。助手回答中可长期复用的学习结论可以保存为 learning，
   但必须得到本轮上下文支持。
8. entities 只允许 project、technology、goal、preference、topic；
   名称应使用稳定、可跨会话复用的实体名，禁止生成“内容”“问题”等空泛实体；
9. 只针对提供的现有相关记忆判断 SAME_TOPIC、SUPPORTS、UPDATES、CONTRADICTS，
   每条新记忆最多输出 3 条高置信关系。新结论替代旧结论时使用 UPDATES；
10. 每个对话都必须同时生成 conversation_title 和 display_summary，即使 items 为空：
   - conversation_title 不超过 20 个字符，直接概括本轮核心主题，必须包含必要的项目名、
     技术名或任务名；禁止“用户提出问题”“一次技术讨论”等空泛标题；
   - display_summary 概括本次对话用户目标、关键事实、最终结论和明确决定。普通对话控制在
     100～300 字；信息密集或原文很长时可以增加，但最多 800 字；
   - 摘要不是原文复制，也不能只写 Agent 做了什么。禁止虚构、夸张和固定套话。
"""


class MemoryDistiller:
    """执行长期记忆抽取、SQLite 落库和搜索索引同步。"""

    def __init__(self, *, llm: BaseChatModel, memory_store: MemoryStore,
                 search_indexer: MemorySearchIndexer) -> None:
        self._llm = llm
        self._memory_store = memory_store
        self._search_indexer = search_indexer
        self.last_error = ""
        self.last_metrics = {"memory_points": 0, "entities": 0, "relations": 0, "tokens": 0}

    def distill_batch(self, *, session_id: str,
                      messages: tuple[SessionMessage, ...],
                      existing_memories: tuple[MemoryPoint, ...]) -> bool:
        """批量处理游标之后的消息；只有完全成功才返回 True。"""

        self.last_metrics = {"memory_points": 0, "entities": 0, "relations": 0, "tokens": 0}
        if not messages:
            return True
        turns = self._group_turns(messages)
        if not turns:
            return True
        origin_type, origin_client = self._origins(messages)
        # 原始对话是 USER_MEMORY 向量/关键词检索的唯一内容来源。
        for user, assistant in turns:
            self._search_indexer.upsert_turn(
                session_id=session_id, user=user, assistant=assistant,
                title=user.content[:48],
            )
        conversation_turns = "\n\n".join(
            "\n".join((
                f"<turn index={index}>",
                f"[user_message_id={user.message_id}] user: {user.content}",
                f"[assistant_message_id={assistant.message_id}] assistant: {assistant.content}",
                "</turn>",
            ))
            for index, (user, assistant) in enumerate(turns, start=1)
        )
        memory_context = "\n".join(
            f"- memory_id={item.memory_id}; type={item.memory_type}; content={item.content}"
            for item in existing_memories
        )
        try:
            self.last_error = ""
            structured = LocalStructuredOutput(self._llm, DistillationOutput)
            output = structured.invoke(
                _DISTILL_PROMPT.format(
                    conversation_turns=conversation_turns,
                    existing_memories=memory_context or "无现有相关记忆",
                )
            )
            items = [item for turn in output.turns for item in turn.items
                     if item.operation in {"add", "update"}]
            self.last_metrics = {
                "memory_points": len(items),
                "entities": len({(entity.name, entity.entity_type) for item in items for entity in item.entities}),
                "relations": sum(len(item.relations) for item in items),
                "tokens": int(structured.last_usage.get("total_tokens") or 0),
            }
            allowed_turns = {
                (user.message_id, assistant.message_id): {
                    user.message_id, assistant.message_id
                }
                for user, assistant in turns
            }
            returned_turn_keys = [
                (item.user_message_id, item.assistant_message_id)
                for item in output.turns
            ]
            expected_turn_keys = set(allowed_turns)
            if (
                set(returned_turn_keys) != expected_turn_keys
                or len(returned_turn_keys) != len(expected_turn_keys)
            ):
                raise ValueError(
                    "蒸馏输出必须与输入完整问答一一对应："
                    f"expected={sorted(expected_turn_keys)}, "
                    f"actual={returned_turn_keys}"
                )
            processed_turns: set[tuple[int, int]] = set()
            for turn_output in output.turns:
                turn_key = (
                    turn_output.user_message_id,
                    turn_output.assistant_message_id,
                )
                allowed_ids = allowed_turns.get(turn_key)
                if allowed_ids is None or turn_key in processed_turns:
                    continue
                processed_turns.add(turn_key)
                default_ids = sorted(allowed_ids)
                user, assistant = next(
                    pair for pair in turns
                    if (pair[0].message_id, pair[1].message_id) == turn_key
                )
                self._memory_store.save_turn_presentation(
                    user_message_id=user.message_id,
                    assistant_message_id=assistant.message_id,
                    conversation_title=(
                        turn_output.conversation_title.strip()
                        or user.content.strip()[:48]
                    )[:20],
                    display_summary=(
                        turn_output.display_summary.strip()
                        or f"用户提出了“{user.content.strip()[:32]}”，Agent 给出了相应的分析与回答。"
                    )[:800],
                )
                for item in turn_output.items:
                    item_source_ids = [
                        item_id for item_id in item.source_message_ids
                        if item_id in allowed_ids
                    ]
                    self._apply(
                        item, item_source_ids or default_ids,
                        origin_type=origin_type, origin_client=origin_client,
                    )
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            logger.warning("对话长期记忆蒸馏失败", exc_info=True)
            return False
        return True

    @staticmethod
    def _group_turns(
        messages: tuple[SessionMessage, ...],
    ) -> tuple[tuple[SessionMessage, SessionMessage], ...]:
        """把扁平消息流组成完整 user/assistant 轮次。

        长期蒸馏只消费完整轮次。孤立消息不会被错误绑定到相邻轮次；正常生产写入通过
        save_turn 原子保存，所以这里主要承担输出契约校验和历史数据防御。
        """

        turns: list[tuple[SessionMessage, SessionMessage]] = []
        pending_user: SessionMessage | None = None
        for message in messages:
            if message.role == "user":
                pending_user = message
                continue
            if message.role == "assistant" and pending_user is not None:
                turns.append((pending_user, message))
                pending_user = None
        return tuple(turns)

    def _apply(
        self, item: DistillationItem, source_ids: list[int], *,
        origin_type: str, origin_client: str,
    ) -> None:
        if item.operation == "noop" or not item.content.strip():
            return
        if item.operation == "update":
            self._update(item, source_ids, origin_type, origin_client)
        elif item.operation == "delete":
            self._delete(item)
        else:
            self._add(item, source_ids, origin_type, origin_client)

    def _add(
        self, item: DistillationItem, source_ids: list[int],
        origin_type: str, origin_client: str,
    ) -> None:
        memory_id = compute_memory_id(item.content, source_ids)
        if self._memory_store.get(memory_id) is not None:
            existing = self._memory_store.get(memory_id)
            if existing is not None:
                refreshed = MemoryPoint(
                    memory_id=existing.memory_id,
                    content=existing.content,
                    summary=existing.summary,
                    memory_type=existing.memory_type,
                    importance=max(existing.importance, item.importance),
                    source_message_ids=sorted(
                        set(existing.source_message_ids) | set(source_ids)
                    ),
                    topics=sorted(set(existing.topics) | set(item.topics)),
                    subject=item.subject or existing.subject,
                    confidence=max(existing.confidence, item.confidence),
                    entities=sorted(set(existing.entities) | {
                        (entity.name, entity.entity_type) for entity in item.entities
                    }),
                    created_at=existing.created_at,
                    last_accessed_at=_utc_now_iso(),
                    access_count=existing.access_count + 1,
                    status="active",
                    origin_type=self._merge_origin(existing.origin_type, origin_type),
                    origin_client=self._merge_origin(existing.origin_client, origin_client),
                )
                self._memory_store.save(refreshed)
                self._save_declared_relations(refreshed, item)
            return
        point = MemoryPoint(
            memory_id=memory_id, content=item.content,
            summary=item.summary or item.content[:80], memory_type=item.memory_type,
            importance=item.importance, topics=item.topics,
            subject=item.subject, confidence=item.confidence,
            entities=[(entity.name, entity.entity_type) for entity in item.entities],
            source_message_ids=source_ids, created_at=_utc_now_iso(),
            last_accessed_at=_utc_now_iso(), access_count=1, status="active",
            origin_type=origin_type, origin_client=origin_client,
        )
        self._memory_store.save(point)
        self._save_declared_relations(point, item)

    def _update(
        self, item: DistillationItem, source_ids: list[int],
        origin_type: str, origin_client: str,
    ) -> None:
        target_id = (item.target_memory_id or "").strip()
        existing = self._memory_store.get(target_id) if target_id else None
        if existing is None:
            self._add(item, source_ids, origin_type, origin_client)
            return
        # 更新保留历史：旧记忆标记 superseded，新结论保存为新节点并连接 UPDATES。
        self._memory_store.save(MemoryPoint(
            memory_id=existing.memory_id, content=existing.content,
            summary=existing.summary, memory_type=existing.memory_type,
            importance=existing.importance,
            source_message_ids=existing.source_message_ids, topics=existing.topics,
            subject=existing.subject, confidence=existing.confidence,
            entities=existing.entities, created_at=existing.created_at,
            last_accessed_at=existing.last_accessed_at,
            access_count=existing.access_count, status="superseded",
            origin_type=existing.origin_type, origin_client=existing.origin_client,
        ))
        updated = MemoryPoint(
            memory_id=compute_memory_id(item.content, source_ids),
            content=item.content.strip(),
            summary=item.summary.strip() or existing.summary,
            memory_type=item.memory_type or existing.memory_type,
            importance=item.importance,
            source_message_ids=source_ids,
            topics=sorted(set(existing.topics) | set(item.topics)),
            subject=item.subject or existing.subject, confidence=item.confidence,
            entities=[(entity.name, entity.entity_type) for entity in item.entities],
            created_at=_utc_now_iso(), last_accessed_at=_utc_now_iso(),
            access_count=1, status="active",
            origin_type=self._merge_origin(existing.origin_type, origin_type),
            origin_client=self._merge_origin(existing.origin_client, origin_client),
        )
        self._memory_store.save(updated)
        self._memory_store.save_relation(MemoryRelation(
            relation_id=self._memory_store.relation_id(
                "memory_point", updated.memory_id, "memory_point",
                existing.memory_id, "UPDATES",
            ),
            source_type="memory_point", source_id=updated.memory_id,
            target_type="memory_point", target_id=existing.memory_id,
            relation_type="UPDATES", confidence=item.confidence,
        ))
        self._save_declared_relations(updated, item)

    def _delete(self, item: DistillationItem) -> None:
        target_id = (item.target_memory_id or "").strip()
        existing = self._memory_store.get(target_id) if target_id else None
        if existing is None:
            return
        self._memory_store.delete(existing.memory_id)

    def _save_declared_relations(
        self, point: MemoryPoint, item: DistillationItem,
    ) -> None:
        """仅保存模型针对预召回候选作出的受控关系判断。"""

        for candidate in item.relations[:3]:
            if candidate.target_memory_id == point.memory_id:
                continue
            if self._memory_store.get(candidate.target_memory_id) is None:
                continue
            self._memory_store.save_relation(MemoryRelation(
                relation_id=self._memory_store.relation_id(
                    "memory_point", point.memory_id, "memory_point",
                    candidate.target_memory_id, candidate.relation_type,
                ),
                source_type="memory_point", source_id=point.memory_id,
                target_type="memory_point", target_id=candidate.target_memory_id,
                relation_type=candidate.relation_type,
                confidence=candidate.confidence,
            ))

    @staticmethod
    def _origins(messages: tuple[SessionMessage, ...]) -> tuple[str, str]:
        """同批消息通常同源；跨源合并时显式标记 mixed，避免错误归属。"""

        types = {message.origin_type for message in messages}
        clients = {message.origin_client for message in messages}
        return (
            next(iter(types)) if len(types) == 1 else "mixed",
            next(iter(clients)) if len(clients) == 1 else "mixed",
        )

    @staticmethod
    def _merge_origin(current: str, incoming: str) -> str:
        return current if current == incoming else "mixed"

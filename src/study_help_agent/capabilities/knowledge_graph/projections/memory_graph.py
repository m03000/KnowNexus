"""记忆图谱 Adapter 与一跳 Graph RAG 适配器。

前端展示与 RAG 检索职责分离：
- 星点 = conversation_turns 中的一次完整 user/assistant 问答；
- 点击星点直接从 SQLite 读取原始问答，不查询向量库；
- 原始对话在 Qdrant 中提供语义入口，蒸馏记忆点和关系只保存在 SQLite。
"""
from __future__ import annotations

from study_help_agent.capabilities.long_term_memory.memory_store import (
    MemoryPoint,
    MemoryStore,
)
from study_help_agent.capabilities.rag.infrastructure.qdrant_store import QdrantChunkStore
from study_help_agent.capabilities.knowledge_graph.application import MemoryGraphQuery
from study_help_agent.capabilities.rag.domain.models import RetrievedChunk


class MemoryGraphAdapter:
    """把原始对话轮次暴露为统一图谱数据（GraphQueryService 的记忆域）。"""

    def __init__(
        self,
        *,
        conversation_repository,
        memory_store: MemoryStore,
        vector_store: QdrantChunkStore | None = None,
        full_limit: int | None = None,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._memory_store = memory_store
        self._vector_store = vector_store
        self._full_limit = full_limit

    def graph_data(self, request: MemoryGraphQuery) -> dict:
        """返回对话概括—记忆点—实体图；原始问答仅在用户点击后读取。"""

        actual_limit = max(int(request.limit), 0)
        if self._full_limit is not None and actual_limit > 0:
            actual_limit = min(actual_limit, self._full_limit)
        graph = (
            self._memory_store.graph_snapshot(query=request.query or "", limit=actual_limit)
            if actual_limit > 0
            else self._memory_store.graph_snapshot(query=request.query or "")
        )
        turns = (
            self._conversation_repository.list_conversation_turns(
                query=request.query or None, limit=actual_limit,
            )
            if actual_limit > 0
            else self._conversation_repository.list_conversation_turns(
                query=request.query or None,
            )
        )
        turn_nodes = [self._to_node(turn) for turn in turns]
        turn_by_message_id = {
            int(message_id): turn
            for turn in turns
            for message_id in (
                turn["user_message_id"], turn["assistant_message_id"],
            )
        }
        source_edges = []
        linked_turn_ids: set[str] = set()
        for node in graph["nodes"]:
            if node.get("node_type") != "memory_point":
                continue
            source_ids = node.get("payload", {}).get("source_message_ids", [])
            related_turns = {
                turn_by_message_id[int(message_id)]["turn_id"]
                for message_id in source_ids
                if int(message_id) in turn_by_message_id
            }
            for turn_id in related_turns:
                linked_turn_ids.add(str(turn_id))
                source_edges.append({
                    "id": f"derived:{node['id']}:{turn_id}",
                    "source": node["id"],
                    "target": f"turn:{turn_id}",
                    "label": "DERIVED_FROM",
                    "edge_type": "DERIVED_FROM",
                    "weight": 1.0,
                })
        # 所有完整轮次都进入目录和星图；是否已经蒸馏只影响 DERIVED_FROM 边，
        # 不能让尚未达到阈值或蒸馏暂时失败的会话从目录消失。
        visible_turn_nodes = turn_nodes
        return {
            "nodes": [*graph["nodes"], *visible_turn_nodes],
            "edges": [*graph["edges"], *source_edges],
            "metadata": {
                "result_count": len(graph["nodes"]) + len(visible_turn_nodes),
                "query": request.query,
            },
        }

    def turn_detail(self, turn_id: str) -> dict:
        """返回一个星点代表的完整原始问答。"""

        turn = self._conversation_repository.get_conversation_turn(turn_id)
        return turn or {"turn_id": turn_id, "found": False}

    def trace(self, memory_id: str) -> dict:
        """保留RAG/MCP使用的蒸馏记忆证据追溯，不参与前端星点加载。"""

        trace = self._memory_store.trace_memory(memory_id)
        if trace is None:
            return {"memory": None, "messages": [], "sessions": []}
        return {
            "memory": {
                "memory_id": trace.memory.memory_id,
                "content": trace.memory.content,
                "summary": trace.memory.summary,
                "memory_type": trace.memory.memory_type,
                "importance": trace.memory.importance,
                "topics": trace.memory.topics,
                "access_count": trace.memory.access_count,
                "status": trace.memory.status,
                "created_at": trace.memory.created_at,
                "last_accessed_at": trace.memory.last_accessed_at,
                "origin_type": trace.memory.origin_type,
                "origin_client": trace.memory.origin_client,
            },
            "messages": [
                {
                    "message_id": message.message_id,
                    "session_id": message.session_id,
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                    "conversation_title": message.conversation_title,
                    "origin_type": message.origin_type,
                    "origin_client": message.origin_client,
                }
                for message in trace.messages
            ],
            "sessions": [
                {
                    "session_id": session.session_id,
                    "title": session.title,
                    "message_count": session.message_count,
                    "started_at": session.started_at,
                    "ended_at": session.ended_at,
                    "origin_type": session.origin_type,
                    "origin_client": session.origin_client,
                }
                for session in trace.sessions
            ],
        }

    def semantic_candidates(self, memory_id: str, limit: int = 5) -> list[dict]:
        """用记忆正文做向量查询，并剔除自身及已经建立的一跳关系。"""

        memory = self._memory_store.get(memory_id)
        if memory is None or self._vector_store is None:
            return []
        excluded = {memory_id, *(item.memory_id for item in self._memory_store.related_memories(memory_id, limit=50))}
        chunks = self._vector_store.retrieve_scoped(
            memory.content, max(limit * 6, 24), ("user_memory",),
        )
        ranked_candidates: list[MemoryPoint] = []
        for chunk in chunks:
            values = chunk.metadata.get("message_ids", [])
            if isinstance(values, list):
                message_ids = [int(value) for value in values if str(value).isdigit()]
                ranked_candidates.extend(
                    self._memory_store.memories_for_messages(message_ids, limit=10)
                )
        result: list[dict] = []
        seen: set[str] = set()
        for candidate in ranked_candidates:
            if candidate.memory_id in excluded or candidate.memory_id in seen:
                continue
            seen.add(candidate.memory_id)
            result.append(self._memory_point_node(candidate))
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _memory_point_node(memory: MemoryPoint) -> dict:
        return {
            "id": memory.memory_id,
            "label": memory.summary or memory.content[:48],
            "node_type": "memory_point",
            "domain": "memory",
            "description": memory.content,
            "payload": {
                "memory_id": memory.memory_id,
                "memory_type": memory.memory_type,
                "summary": memory.summary,
                "content": memory.content,
                "importance": memory.importance,
                "topics": memory.topics,
                "status": memory.status,
                "created_at": memory.created_at,
                "origin_type": memory.origin_type,
                "origin_client": memory.origin_client,
            },
        }

    @staticmethod
    def _to_node(turn: dict) -> dict:
        """列表节点只携带摘要；完整回答在点击后按 turn_id 查询。"""

        return {
            "id": f"turn:{turn['turn_id']}",
            "label": str(turn.get("conversation_title") or turn["user_message"])[:20],
            "node_type": "conversation_turn",
            "domain": "memory",
            "summary": str(turn.get("display_summary") or turn["assistant_message"])[:800],
            "payload": {
                "turn_id": turn["turn_id"],
                "session_id": turn["session_id"],
                "title": turn["title"],
                "user_message_id": turn["user_message_id"],
                "assistant_message_id": turn["assistant_message_id"],
                "created_at": turn["created_at"],
                "origin_type": turn["origin_type"],
                "origin_client": turn["origin_client"],
            },
        }


class MemoryStructureRetriever:
    """原始对话向量入口 + SQLite 记忆点 FTS + 一跳关系扩展。"""

    def __init__(
        self,
        *,
        memory_store: MemoryStore,
        vector_store: QdrantChunkStore,
        candidate_limit: int = 200,
    ) -> None:
        self._memory_store = memory_store
        self._vector_store = vector_store
        self._candidate_limit = candidate_limit

    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        """找到入口记忆点后只扩展一跳，总节点数受 limit/10 双重限制。"""

        actual_limit = min(max(limit, 1), 10)
        raw_chunks = self._vector_store.retrieve_scoped(
            query, actual_limit, ("user_memory",)
        )
        message_ids: list[int] = []
        for chunk in raw_chunks:
            values = chunk.metadata.get("message_ids", [])
            if isinstance(values, list):
                message_ids.extend(int(value) for value in values if str(value).isdigit())

        entries = [
            *self._memory_store.memories_for_messages(message_ids, limit=actual_limit),
            *self._memory_store.search(query, limit=actual_limit),
        ]
        unique: dict[str, MemoryPoint] = {item.memory_id: item for item in entries}
        for entry in tuple(unique.values()):
            for related in self._memory_store.related_memories(
                entry.memory_id, limit=actual_limit
            ):
                unique.setdefault(related.memory_id, related)
                if len(unique) >= actual_limit:
                    break
            if len(unique) >= actual_limit:
                break
        return [self._to_chunk(item) for item in tuple(unique.values())[:actual_limit]]

    def _to_chunk(self, memory: MemoryPoint) -> RetrievedChunk:
        trace = self._memory_store.trace_memory(memory.memory_id)
        source_excerpt = ""
        if trace and trace.messages:
            source_excerpt = "\n".join(
                f"{message.role}: {message.content}" for message in trace.messages[:2]
            )
        text = f"记忆点：{memory.content}"
        if source_excerpt:
            text += f"\n来源对话：\n{source_excerpt}"
        return RetrievedChunk(
            chunk_id=f"memory-point:{memory.memory_id}",
            text=text,
            space="user_memory",
            asset_type="memory_point",
            title=memory.summary or memory.content[:48],
            metadata={
                "memory_id": memory.memory_id,
                "memory_type": memory.memory_type,
                "topics": memory.topics,
                "source_message_ids": memory.source_message_ids,
                "status": memory.status,
            },
            retrieval_channels=("graph",),
        )

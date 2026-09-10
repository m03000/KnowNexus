"""长期记忆点、实体关系图和原始对话溯源的 SQLite 实现。

原始问答由对话仓储保存，并投影到 USER_MEMORY 检索库；本模块只把蒸馏记忆点、
实体、关系和来源映射保存到 SQLite，避免把摘要与原始证据混成同一种检索文档。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol

from study_help_agent.capabilities.knowledge_ingestion.infrastructure.lexical_index_writer import (
    LexicalTextEncoder,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class MemoryPoint:
    """一条记忆点。memory_id 由蒸馏器按 sha256(content+source_ids) 计算，幂等去重。"""

    memory_id: str
    content: str
    summary: str
    memory_type: str
    importance: int
    source_message_ids: list[int]
    topics: list[str] = field(default_factory=list)
    subject: str = "user"
    confidence: float = 0.8
    entities: list[tuple[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    last_accessed_at: str = field(default_factory=utc_now)
    access_count: int = 0
    status: str = "active"
    origin_type: str = "internal"
    origin_client: str = "personal_agent"


@dataclass(frozen=True, slots=True)
class MemoryRelation:
    """记忆图中的规范边，可连接记忆点、实体和原始对话轮次。"""

    relation_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    confidence: float = 0.8


@dataclass(frozen=True, slots=True)
class MemoryTraceMessage:
    """记忆溯源中的一条来源消息（JOIN conversations 携带会话标题）。"""

    message_id: int
    session_id: str
    role: str
    content: str
    created_at: str
    conversation_title: str
    origin_type: str = "internal"
    origin_client: str = "personal_agent"


@dataclass(frozen=True, slots=True)
class MemoryTraceSession:
    """来源消息按会话聚类的时间线条目。"""

    session_id: str
    title: str
    message_count: int
    started_at: str
    ended_at: str
    origin_type: str = "internal"
    origin_client: str = "personal_agent"


@dataclass(frozen=True, slots=True)
class MemoryTrace:
    """一条记忆点的完整溯源：原话序列 + 会话聚类。"""

    memory: MemoryPoint
    messages: tuple[MemoryTraceMessage, ...]
    sessions: tuple[MemoryTraceSession, ...]


class MemoryStore(Protocol):
    def save(self, memory: MemoryPoint) -> None: ...
    def get(self, memory_id: str) -> MemoryPoint | None: ...
    def get_by_content(self, content: str) -> MemoryPoint | None: ...
    def touch(self, memory_id: str) -> None: ...
    def delete(self, memory_id: str) -> None: ...
    def list_memories(self, *, status: str = "active", limit: int = 0) -> list[MemoryPoint]: ...
    def messages_for_memory(self, memory_id: str) -> list[sqlite3.Row]: ...
    def trace_memory(self, memory_id: str) -> MemoryTrace | None: ...
    def save_turn_presentation(self, *, user_message_id: int,
                               assistant_message_id: int,
                               conversation_title: str,
                               display_summary: str) -> None: ...
    def search(self, query: str, *, limit: int = 5) -> tuple[MemoryPoint, ...]: ...
    def save_relation(self, relation: MemoryRelation) -> None: ...
    def related_memories(self, memory_id: str, *, limit: int = 10) -> tuple[MemoryPoint, ...]: ...
    def memories_for_messages(self, message_ids: list[int], *, limit: int = 10) -> tuple[MemoryPoint, ...]: ...
    def graph_snapshot(self, *, query: str = "", limit: int = 0) -> dict: ...
    @staticmethod
    def relation_id(source_type: str, source_id: str, target_type: str,
                    target_id: str, relation_type: str) -> str: ...


class SqliteMemoryStore:
    """基于 SqliteConnectionFactory 的记忆点仓储（save 为 UPSERT 语义）。"""

    def __init__(self, connections) -> None:
        self._connections = connections
        self._lexical_encoder = LexicalTextEncoder()

    def save(self, memory: MemoryPoint) -> None:
        with self._connections.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_points (
                    memory_id, content, summary, memory_type, subject, topic,
                    importance, confidence, created_at, updated_at, last_accessed_at,
                    access_count, status, origin_type, origin_client
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    content = excluded.content,
                    summary = excluded.summary,
                    memory_type = excluded.memory_type,
                    subject = excluded.subject,
                    topic = excluded.topic,
                    importance = excluded.importance,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at,
                    last_accessed_at = excluded.last_accessed_at,
                    access_count = excluded.access_count,
                    status = excluded.status,
                    origin_type = excluded.origin_type,
                    origin_client = excluded.origin_client
                """,
                (
                    memory.memory_id,
                    memory.content,
                    memory.summary,
                    memory.memory_type,
                    memory.subject,
                    memory.topics[0] if memory.topics else "",
                    memory.importance,
                    memory.confidence,
                    memory.created_at,
                    utc_now(),
                    memory.last_accessed_at,
                    memory.access_count,
                    memory.status,
                    memory.origin_type,
                    memory.origin_client,
                ),
            )
            conn.execute("DELETE FROM memory_points_fts WHERE memory_id = ?", (memory.memory_id,))
            conn.execute(
                "INSERT INTO memory_points_fts(memory_id, content, summary, topic) VALUES (?, ?, ?, ?)",
                (memory.memory_id, self._lexical_encoder.encode(memory.content),
                 self._lexical_encoder.encode(memory.summary),
                 self._lexical_encoder.encode(" ".join(memory.topics))),
            )
            self._save_sources(conn, memory)
            self._save_entities(conn, memory)

    def get(self, memory_id: str) -> MemoryPoint | None:
        with self._connections.connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_points WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return self._row_to_point(row) if row else None

    def get_by_content(self, content: str) -> MemoryPoint | None:
        with self._connections.connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_points WHERE content = ? AND status = 'active' "
                "ORDER BY last_accessed_at DESC LIMIT 1",
                (content,),
            ).fetchone()
        return self._row_to_point(row) if row else None

    def touch(self, memory_id: str) -> None:
        with self._connections.connect() as conn:
            conn.execute(
                "UPDATE memory_points SET last_accessed_at = ?, access_count = access_count + 1 "
                "WHERE memory_id = ?",
                (utc_now(), memory_id),
            )

    def delete(self, memory_id: str) -> None:
        """软删除：status 置 archived，保留溯源证据。"""
        with self._connections.connect() as conn:
            conn.execute(
                "UPDATE memory_points SET status = 'archived', updated_at = ? WHERE memory_id = ?",
                (utc_now(), memory_id),
            )

    def list_memories(self, *, status: str = "active", limit: int = 0) -> list[MemoryPoint]:
        with self._connections.connect() as conn:
            sql = "SELECT * FROM memory_points WHERE status = ? ORDER BY created_at DESC"
            rows = conn.execute(
                f"{sql} LIMIT ?" if limit > 0 else sql,
                (status, limit) if limit > 0 else (status,),
            ).fetchall()
        return [self._row_to_point(row) for row in rows]

    def search(self, query: str, *, limit: int = 5) -> tuple[MemoryPoint, ...]:
        """使用 SQLite FTS5 召回少量候选记忆，供关系判断与图检索使用。"""

        actual_limit = min(max(limit, 1), 10)
        terms = tuple(dict.fromkeys(
            term.casefold() for term in self._lexical_encoder.terms(query)
            if term.strip()
        ))
        if not terms:
            return tuple(self.list_memories(limit=actual_limit))
        expression = " OR ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:24]
        )
        with self._connections.connect() as conn:
            rows = conn.execute(
                """SELECT p.* FROM memory_points_fts f
                   JOIN memory_points p ON p.memory_id=f.memory_id
                   WHERE memory_points_fts MATCH ? AND p.status='active'
                   ORDER BY bm25(memory_points_fts), p.importance DESC
                   LIMIT ?""",
                (expression, actual_limit),
            ).fetchall()
        return tuple(self._row_to_point(row) for row in rows)

    def messages_for_memory(self, memory_id: str) -> list[sqlite3.Row]:
        """溯源：记忆点 → messages 原话（source_message_ids 外键 JOIN）。"""
        point = self.get(memory_id)
        if point is None or not point.source_message_ids:
            return []
        placeholders = ",".join("?" for _ in point.source_message_ids)
        with self._connections.connect() as conn:
            return conn.execute(
                f"SELECT message_id, session_id, role, content, created_at FROM messages "
                f"WHERE message_id IN ({placeholders}) ORDER BY message_id",
                [int(i) for i in point.source_message_ids],
            ).fetchall()

    def trace_memory(self, memory_id: str) -> MemoryTrace | None:
        """溯源 JOIN：memories → messages → conversations，并按会话聚类时间线。"""

        point = self.get(memory_id)
        if point is None or not point.source_message_ids:
            return None
        placeholders = ",".join("?" for _ in point.source_message_ids)
        with self._connections.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.message_id, m.session_id, m.role, m.content, m.created_at,
                       COALESCE(c.title, '') AS conversation_title,
                       COALESCE(c.origin_type, 'internal') AS origin_type,
                       COALESCE(c.origin_client, 'personal_agent') AS origin_client
                FROM messages m
                LEFT JOIN conversations c ON c.session_id = m.session_id
                WHERE m.message_id IN ({placeholders})
                ORDER BY m.message_id
                """,
                [int(i) for i in point.source_message_ids],
            ).fetchall()
        messages = tuple(
            MemoryTraceMessage(
                message_id=int(row["message_id"]),
                session_id=str(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                conversation_title=str(row["conversation_title"]),
                origin_type=str(row["origin_type"]),
                origin_client=str(row["origin_client"]),
            )
            for row in rows
        )
        return MemoryTrace(
            memory=point,
            messages=messages,
            sessions=self._cluster_sessions(rows),
        )

    @staticmethod
    def _cluster_sessions(
        rows: list[sqlite3.Row],
    ) -> tuple[MemoryTraceSession, ...]:
        """按 session_id 把来源消息聚类成会话时间线（ISO 时间可直接字典序比较）。"""

        grouped: dict[str, list[str]] = {}
        titles: dict[str, str] = {}
        origins: dict[str, tuple[str, str]] = {}
        for row in rows:
            session_id = str(row["session_id"])
            grouped.setdefault(session_id, []).append(str(row["created_at"]))
            titles.setdefault(session_id, str(row["conversation_title"]))
            origins.setdefault(
                session_id,
                (str(row["origin_type"]), str(row["origin_client"])),
            )
        sessions = [
            MemoryTraceSession(
                session_id=session_id,
                title=titles[session_id],
                message_count=len(times),
                started_at=min(times),
                ended_at=max(times),
                origin_type=origins[session_id][0],
                origin_client=origins[session_id][1],
            )
            for session_id, times in grouped.items()
        ]
        return tuple(sorted(sessions, key=lambda s: s.started_at))

    def save_turn_presentation(
        self, *, user_message_id: int, assistant_message_id: int,
        conversation_title: str, display_summary: str,
    ) -> None:
        """把同一次蒸馏顺带生成的展示元数据写回对应原始对话轮次。"""

        with self._connections.connect() as conn:
            conn.execute(
                """UPDATE conversation_turns
                   SET conversation_title = ?, display_summary = ?
                   WHERE user_message_id = ? AND assistant_message_id = ?""",
                (
                    conversation_title[:20],
                    display_summary[:800],
                    user_message_id,
                    assistant_message_id,
                ),
            )

    def _save_sources(self, conn: sqlite3.Connection, memory: MemoryPoint) -> None:
        """规范化保存来源，并同时建立 DERIVED_FROM 图边。"""

        for message_id in memory.source_message_ids:
            source = conn.execute(
                """SELECT m.session_id, COALESCE(t.turn_id, '') AS turn_id
                   FROM messages m LEFT JOIN conversation_turns t
                     ON t.user_message_id=m.message_id OR t.assistant_message_id=m.message_id
                   WHERE m.message_id=? LIMIT 1""",
                (message_id,),
            ).fetchone()
            if source is None:
                continue
            turn_id = str(source["turn_id"])
            conn.execute(
                """INSERT OR IGNORE INTO memory_sources
                   (memory_id, session_id, turn_id, message_id) VALUES (?, ?, ?, ?)""",
                (memory.memory_id, source["session_id"], turn_id, message_id),
            )
            self.save_relation(MemoryRelation(
                relation_id=self.relation_id(
                    "memory_point", memory.memory_id, "conversation_turn", turn_id,
                    "DERIVED_FROM",
                ),
                source_type="memory_point", source_id=memory.memory_id,
                target_type="conversation_turn", target_id=turn_id,
                relation_type="DERIVED_FROM", confidence=1.0,
            ), connection=conn)

    def _save_entities(self, conn: sqlite3.Connection, memory: MemoryPoint) -> None:
        """确定性规范化实体并建立 ABOUT 边。"""

        allowed = {"project", "technology", "goal", "preference", "topic"}
        candidates = [*memory.entities, *((topic, "topic") for topic in memory.topics)]
        for name, entity_type in candidates:
            normalized = "".join(name.casefold().split())
            if not normalized or entity_type not in allowed:
                continue
            entity_id = sha256(f"default:{entity_type}:{normalized}".encode()).hexdigest()
            conn.execute(
                """INSERT OR IGNORE INTO memory_entities
                   (entity_id, user_id, name, normalized_name, entity_type)
                   VALUES (?, 'default', ?, ?, ?)""",
                (entity_id, name.strip(), normalized, entity_type),
            )
            self.save_relation(MemoryRelation(
                relation_id=self.relation_id(
                    "memory_point", memory.memory_id, "entity", entity_id, "ABOUT"
                ),
                source_type="memory_point", source_id=memory.memory_id,
                target_type="entity", target_id=entity_id,
                relation_type="ABOUT", confidence=memory.confidence,
            ), connection=conn)

    def save_relation(
        self, relation: MemoryRelation, *, connection: sqlite3.Connection | None = None,
    ) -> None:
        """幂等保存关系边，并允许复用记忆点写入事务。"""

        def execute(conn: sqlite3.Connection) -> None:
            conn.execute(
                """INSERT INTO memory_relations
                   (relation_id, source_type, source_id, target_type, target_id,
                    relation_type, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_type, source_id, target_type, target_id, relation_type)
                   DO UPDATE SET confidence=MAX(confidence, excluded.confidence)""",
                (relation.relation_id, relation.source_type, relation.source_id,
                 relation.target_type, relation.target_id, relation.relation_type,
                 relation.confidence),
            )
        if connection is not None:
            execute(connection)
            return
        with self._connections.connect() as conn:
            execute(conn)

    def related_memories(
        self, memory_id: str, *, limit: int = 10,
    ) -> tuple[MemoryPoint, ...]:
        """一跳扩展直接关系与共享实体关系，最多返回十条有效记忆。"""

        priorities = {"UPDATES": 4, "CONTRADICTS": 3, "SUPPORTS": 2, "SAME_TOPIC": 1}
        with self._connections.connect() as conn:
            direct = conn.execute(
                """SELECT relation_type,
                          CASE WHEN source_id=? THEN target_id ELSE source_id END AS memory_id
                   FROM memory_relations
                   WHERE relation_type IN ('UPDATES','CONTRADICTS','SUPPORTS','SAME_TOPIC')
                     AND ((source_type='memory_point' AND source_id=?)
                       OR (target_type='memory_point' AND target_id=?))""",
                (memory_id, memory_id, memory_id),
            ).fetchall()
            shared = conn.execute(
                """SELECT DISTINCT other.source_id AS memory_id,
                          'SAME_TOPIC' AS relation_type
                   FROM memory_relations mine JOIN memory_relations other
                     ON mine.target_type='entity' AND other.target_type='entity'
                    AND mine.target_id=other.target_id
                   WHERE mine.source_type='memory_point' AND mine.source_id=?
                     AND mine.relation_type='ABOUT' AND other.relation_type='ABOUT'
                     AND other.source_id!=?""",
                (memory_id, memory_id),
            ).fetchall()
        ranked = sorted(
            {(str(row["memory_id"]), str(row["relation_type"])) for row in (*direct, *shared)},
            key=lambda item: priorities.get(item[1], 0), reverse=True,
        )
        points = [self.get(item_id) for item_id, _ in ranked]
        return tuple(point for point in points if point and point.status == "active")[:limit]

    def memories_for_messages(
        self, message_ids: list[int], *, limit: int = 10,
    ) -> tuple[MemoryPoint, ...]:
        if not message_ids:
            return ()
        placeholders = ",".join("?" for _ in message_ids)
        with self._connections.connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT p.* FROM memory_sources s
                    JOIN memory_points p ON p.memory_id=s.memory_id
                    WHERE s.message_id IN ({placeholders}) AND p.status='active'
                    ORDER BY p.importance DESC, p.updated_at DESC LIMIT ?""",
                [*message_ids, limit],
            ).fetchall()
        return tuple(self._row_to_point(row) for row in rows)

    def graph_snapshot(self, *, query: str = "", limit: int = 0) -> dict:
        """返回前端与图检索共享的实体—记忆点关系数据，不展开原始对话。"""

        actual_limit = max(int(limit), 0)
        points = list(self.search(query, limit=min(actual_limit or 10, 10))) if query else []
        if not points:
            with self._connections.connect() as conn:
                sql = """SELECT * FROM memory_points
                         WHERE status IN ('active', 'superseded', 'conflicted')
                         ORDER BY created_at DESC"""
                rows = conn.execute(
                    f"{sql} LIMIT ?" if actual_limit > 0 else sql,
                    (actual_limit,) if actual_limit > 0 else (),
                ).fetchall()
            points = [self._row_to_point(row) for row in rows]
        point_ids = {point.memory_id for point in points}
        if not point_ids:
            return {"nodes": [], "edges": []}
        placeholders = ",".join("?" for _ in point_ids)
        with self._connections.connect() as conn:
            relations = conn.execute(
                f"""SELECT * FROM memory_relations
                    WHERE (source_type='memory_point' AND source_id IN ({placeholders}))
                       OR (target_type='memory_point' AND target_id IN ({placeholders}))""",
                [*point_ids, *point_ids],
            ).fetchall()
            entity_ids = {
                str(row["target_id"] if row["target_type"] == "entity" else row["source_id"])
                for row in relations
                if row["target_type"] == "entity" or row["source_type"] == "entity"
            }
            entities = []
            if entity_ids:
                entity_placeholders = ",".join("?" for _ in entity_ids)
                entities = conn.execute(
                    f"SELECT * FROM memory_entities WHERE entity_id IN ({entity_placeholders})",
                    list(entity_ids),
                ).fetchall()
        nodes = [{
            "id": f"memory:{point.memory_id}",
            "label": point.summary or point.content[:48],
            "node_type": "memory_point",
            "domain": "memory",
            "summary": point.content,
            "payload": {
                "memory_id": point.memory_id,
                "memory_type": point.memory_type,
                "status": point.status,
                "created_at": point.created_at,
                "origin_type": point.origin_type,
                "origin_client": point.origin_client,
                "source_message_ids": point.source_message_ids,
            },
        } for point in points]
        nodes.extend({
            "id": f"entity:{row['entity_id']}",
            "label": str(row["name"]),
            "node_type": "memory_entity",
            "domain": "memory",
            "summary": str(row["entity_type"]),
            "payload": {
                "entity_id": str(row["entity_id"]),
                "entity_type": str(row["entity_type"]),
            },
        } for row in entities)
        edges = []
        visible_ids = {node["id"] for node in nodes}
        for row in relations:
            source = (
                f"memory:{row['source_id']}" if row["source_type"] == "memory_point"
                else f"entity:{row['source_id']}"
            )
            target = (
                f"memory:{row['target_id']}" if row["target_type"] == "memory_point"
                else f"entity:{row['target_id']}"
            )
            if source in visible_ids and target in visible_ids:
                edges.append({
                    "source": source, "target": target,
                    "edge_type": str(row["relation_type"]),
                    "label": str(row["relation_type"]),
                    "weight": float(row["confidence"]),
                })
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def relation_id(
        source_type: str, source_id: str, target_type: str, target_id: str,
        relation_type: str,
    ) -> str:
        raw = ":".join((source_type, source_id, target_type, target_id, relation_type))
        return sha256(raw.encode()).hexdigest()

    def _row_to_point(self, row: sqlite3.Row) -> MemoryPoint:
        memory_id = str(row["memory_id"])
        with self._connections.connect() as conn:
            source_rows = conn.execute(
                "SELECT message_id FROM memory_sources WHERE memory_id=? ORDER BY message_id",
                (memory_id,),
            ).fetchall()
            entity_rows = conn.execute(
                """SELECT e.name, e.entity_type FROM memory_relations r
                   JOIN memory_entities e ON e.entity_id=r.target_id
                   WHERE r.source_type='memory_point' AND r.source_id=?
                     AND r.target_type='entity' AND r.relation_type='ABOUT'""",
                (memory_id,),
            ).fetchall()
        topic = str(row["topic"] or "")
        return MemoryPoint(
            memory_id=memory_id,
            content=row["content"],
            summary=row["summary"],
            memory_type=row["memory_type"],
            importance=row["importance"],
            source_message_ids=[int(item["message_id"]) for item in source_rows],
            topics=[topic] if topic else [],
            subject=str(row["subject"] or "user"),
            confidence=float(row["confidence"]),
            entities=[(str(item["name"]), str(item["entity_type"])) for item in entity_rows],
            created_at=row["created_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
            status=row["status"],
            origin_type=row["origin_type"],
            origin_client=row["origin_client"],
        )

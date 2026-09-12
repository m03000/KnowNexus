"""短期记忆的 SQLite 仓储；原子保存原始消息、摘要游标和任务状态。"""

import json
from typing import Any

from study_help_agent.capabilities.knowledge_ingestion.infrastructure.lexical_index_writer import LexicalTextEncoder
from study_help_agent.capabilities.conversation_context.domain.models import (
    ActiveTaskContext, SavedTurn, ConversationContextSnapshot, SessionMessage,
)


class SqliteConversationContextRepository:
    """让短期记忆与长期蒸馏共享消息事实，但通过不同游标独立消费。"""

    def __init__(self, connections) -> None:
        self._connections = connections
        self._lexical_encoder = LexicalTextEncoder()

    def get_context_snapshot(self, session_id: str, *,
                           recent_message_limit: int) -> ConversationContextSnapshot:
        with self._connections.connect() as connection:
            conversation = connection.execute(
                """SELECT session_id, summary, summary_until_message_id,
                          distilled_until_message_id, active_context_json,
                          origin_type, origin_client
                   FROM conversations WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
            if conversation is None:
                return ConversationContextSnapshot(session_id=session_id)
            rows = connection.execute(
                """SELECT message_id, role, content, created_at FROM messages
                   WHERE session_id = ? AND message_id > ?
                   ORDER BY message_id DESC LIMIT ?""",
                (session_id, int(conversation["summary_until_message_id"]),
                 recent_message_limit),
            ).fetchall()
        active_data = json.loads(conversation["active_context_json"] or "{}")
        return ConversationContextSnapshot(
            session_id=session_id,
            summary=str(conversation["summary"] or ""),
            summary_until_message_id=int(conversation["summary_until_message_id"]),
            distilled_until_message_id=int(conversation["distilled_until_message_id"]),
            messages=tuple(
                SessionMessage(
                    int(row["message_id"]), str(row["role"]),
                    str(row["content"]), str(row["created_at"]),
                    str(conversation["origin_type"]),
                    str(conversation["origin_client"]),
                )
                for row in reversed(rows)
            ),
            active_context=ActiveTaskContext(
                active_goal=str(active_data.get("active_goal", "")),
                completed_steps=tuple(active_data.get("completed_steps", [])),
                pending_steps=tuple(active_data.get("pending_steps", [])),
                artifact_ids=tuple(active_data.get("artifact_ids", [])),
            ),
        )

    def save_turn(
        self, session_id: str, *, turn_id: str, user_message: str,
        assistant_message: str, origin_type: str = "internal",
        origin_client: str = "personal_agent",
        external_session_id: str | None = None,
        external_turn_id: str | None = None, title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SavedTurn:
        turn_id = turn_id.strip()
        user_message, assistant_message = user_message.strip(), assistant_message.strip()
        if not turn_id or not user_message or not assistant_message:
            raise ValueError("turn_id、用户消息和回答不能为空")
        with self._connections.connect() as connection:
            existing = connection.execute(
                """SELECT session_id, user_message_id, assistant_message_id
                   FROM conversation_turns WHERE turn_id = ?""",
                (turn_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["session_id"]) != session_id:
                    raise ValueError("turn_id 已被其他 session 使用")
                return SavedTurn(
                    session_id, turn_id, int(existing["user_message_id"]),
                    int(existing["assistant_message_id"]),
                )
            existing_conversation = connection.execute(
                "SELECT title, source_metadata_json FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            incoming_metadata = dict(metadata or {})
            existing_metadata: dict[str, Any] = {}
            if existing_conversation is not None:
                try:
                    existing_metadata = json.loads(
                        str(existing_conversation["source_metadata_json"] or "{}")
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    existing_metadata = {}
            # Stable title precedence: a verified title read from the external agent's own
            # session index > a user's local rename > the first generated/fallback title.
            incoming_external_title = (
                title.strip()[:120]
                if incoming_metadata.get("session_index_verified") else ""
            )
            external_title = incoming_external_title or str(
                existing_metadata.get("external_title") or ""
            ).strip()[:120]
            manual_title = str(existing_metadata.get("manual_title") or "").strip()[:120]
            previous_title = (
                str(existing_conversation["title"] or "").strip()[:120]
                if existing_conversation is not None else ""
            )
            resolved_title = external_title or manual_title or previous_title or title.strip()[:120]
            merged_metadata = {**existing_metadata, **incoming_metadata}
            if external_title:
                merged_metadata["external_title"] = external_title
            if manual_title:
                merged_metadata["manual_title"] = manual_title
            connection.execute(
                """INSERT INTO conversations
                       (session_id, title, message_count, created_at, updated_at,
                        origin_type, origin_client, external_session_id,
                        source_metadata_json)
                   VALUES (?, ?, 0, datetime('now'), datetime('now'), ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       updated_at = datetime('now'),
                       title = excluded.title,
                       source_metadata_json = excluded.source_metadata_json""",
                (session_id, resolved_title, origin_type, origin_client,
                 external_session_id, json.dumps(merged_metadata, ensure_ascii=False)),
            )
            user_cursor = connection.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, 'user', ?)",
                (session_id, user_message),
            )
            assistant_cursor = connection.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, 'assistant', ?)",
                (session_id, assistant_message),
            )
            for cursor, role, content in (
                (user_cursor, "user", user_message),
                (assistant_cursor, "assistant", assistant_message),
            ):
                connection.execute(
                    """INSERT INTO messages_fts
                       (message_id, session_id, role, content) VALUES (?, ?, ?, ?)""",
                    (cursor.lastrowid, session_id, role,
                     self._lexical_encoder.encode(content)),
                )
            connection.execute(
                """UPDATE conversations SET message_count = message_count + 2,
                          updated_at = datetime('now') WHERE session_id = ?""",
                (session_id,),
            )
            connection.execute(
                """INSERT INTO conversation_turns
                   (turn_id, session_id, user_message_id, assistant_message_id,
                    origin_type, origin_client, external_turn_id, source_metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (turn_id, session_id, user_cursor.lastrowid,
                 assistant_cursor.lastrowid, origin_type, origin_client,
                 external_turn_id, json.dumps(metadata or {}, ensure_ascii=False)),
            )
        return SavedTurn(session_id, turn_id, int(user_cursor.lastrowid),
                         int(assistant_cursor.lastrowid))

    def get_saved_turn(self, session_id: str, *, turn_id: str) -> SavedTurn:
        """读取已保存轮次的消息主键，用于安全处理 Hook/MCP 重试。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                """SELECT session_id, turn_id, user_message_id, assistant_message_id
                   FROM conversation_turns WHERE turn_id = ? AND session_id = ?""",
                (turn_id, session_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"不存在的对话轮次：{turn_id}")
        return SavedTurn(
            str(row["session_id"]), str(row["turn_id"]),
            int(row["user_message_id"]), int(row["assistant_message_id"]),
        )

    def get_recorded_turn(self, session_id: str, *,
                          turn_id: str) -> tuple[str, str] | None:
        with self._connections.connect() as connection:
            row = connection.execute(
                """SELECT user_message.content AS user_message,
                          assistant_message.content AS assistant_message
                   FROM conversation_turns turn_record
                   JOIN messages user_message
                     ON user_message.message_id = turn_record.user_message_id
                   JOIN messages assistant_message
                     ON assistant_message.message_id = turn_record.assistant_message_id
                   WHERE turn_record.turn_id = ? AND turn_record.session_id = ?""",
                (turn_id, session_id),
            ).fetchone()
        if row is None:
            return None
        return str(row["user_message"]), str(row["assistant_message"])

    def list_conversation_turns(
        self, *, query: str | None = None, limit: int = 0,
    ) -> tuple[dict[str, Any], ...]:
        """按时间倒序读取完整对话轮次的轻量投影，供记忆星图展示。"""

        actual_limit = max(int(limit), 0)
        normalized_query = (query or "").strip()
        where = ""
        parameters: list[Any] = []
        if normalized_query:
            where = """WHERE user_message.content LIKE ?
                       OR assistant_message.content LIKE ?
                       OR turn_record.conversation_title LIKE ?
                       OR turn_record.display_summary LIKE ?"""
            pattern = f"%{normalized_query}%"
            parameters.extend((pattern, pattern, pattern, pattern))
        limit_clause = "LIMIT ?" if actual_limit > 0 else ""
        if actual_limit > 0:
            parameters.append(actual_limit)
        with self._connections.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT turn_record.turn_id, turn_record.session_id,
                       turn_record.user_message_id, turn_record.assistant_message_id,
                       turn_record.created_at,
                       user_message.content AS user_message,
                       assistant_message.content AS assistant_message,
                       COALESCE(NULLIF(turn_record.conversation_title, ''),
                                substr(user_message.content, 1, 48)) AS conversation_title,
                       COALESCE(NULLIF(turn_record.display_summary, ''),
                                substr(assistant_message.content, 1, 160)) AS display_summary,
                       COALESCE(NULLIF(conversation.title, ''),
                                substr(user_message.content, 1, 48), '未命名对话') AS title,
                       COALESCE(turn_record.origin_type, conversation.origin_type,
                                'internal') AS origin_type,
                       COALESCE(turn_record.origin_client, conversation.origin_client,
                                'personal_agent') AS origin_client,
                       conversation.distilled_until_message_id,
                       CASE
                         WHEN turn_record.assistant_message_id <= conversation.distilled_until_message_id THEN 'distilled'
                         WHEN EXISTS (
                           SELECT 1 FROM memory_processing_leases lease
                           WHERE lease.session_id = turn_record.session_id
                             AND lease.purpose = 'long_consolidation'
                             AND lease.expires_at > CAST(strftime('%s', 'now') AS INTEGER)
                         ) THEN 'processing'
                         ELSE 'pending'
                       END AS distillation_status
                FROM conversation_turns turn_record
                JOIN messages user_message
                  ON user_message.message_id = turn_record.user_message_id
                JOIN messages assistant_message
                  ON assistant_message.message_id = turn_record.assistant_message_id
                JOIN conversations conversation
                  ON conversation.session_id = turn_record.session_id
                {where}
                ORDER BY turn_record.created_at DESC, turn_record.user_message_id DESC
                {limit_clause}
                """,
                parameters,
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def get_conversation_turn(self, turn_id: str) -> dict[str, Any] | None:
        """读取一个星点对应的完整原始提问、回答及来源信息。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                """
                SELECT turn_record.turn_id, turn_record.session_id,
                       turn_record.user_message_id, turn_record.assistant_message_id,
                       turn_record.created_at,
                       user_message.content AS user_message,
                       assistant_message.content AS assistant_message,
                       COALESCE(NULLIF(turn_record.conversation_title, ''),
                                substr(user_message.content, 1, 48)) AS conversation_title,
                       COALESCE(NULLIF(turn_record.display_summary, ''),
                                substr(assistant_message.content, 1, 160)) AS display_summary,
                       COALESCE(NULLIF(conversation.title, ''),
                                substr(user_message.content, 1, 48), '未命名对话') AS title,
                       COALESCE(turn_record.origin_type, conversation.origin_type,
                                'internal') AS origin_type,
                       COALESCE(turn_record.origin_client, conversation.origin_client,
                                'personal_agent') AS origin_client,
                       conversation.external_session_id
                FROM conversation_turns turn_record
                JOIN messages user_message
                  ON user_message.message_id = turn_record.user_message_id
                JOIN messages assistant_message
                  ON assistant_message.message_id = turn_record.assistant_message_id
                JOIN conversations conversation
                  ON conversation.session_id = turn_record.session_id
                WHERE turn_record.turn_id = ?
                """,
                (turn_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def acquire_lease(self, session_id: str, *, purpose: str, owner_id: str,
                      ttl_seconds: int = 300) -> bool:
        """跨进程领取 session 级处理租约；过期租约可被新执行者接管。"""

        with self._connections.connect() as connection:
            changed = connection.execute(
                """INSERT INTO memory_processing_leases
                       (session_id, purpose, owner_id, expires_at)
                   VALUES (?, ?, ?, CAST(strftime('%s', 'now') AS INTEGER) + ?)
                   ON CONFLICT(session_id, purpose) DO UPDATE SET
                       owner_id = excluded.owner_id,
                       expires_at = excluded.expires_at
                   WHERE memory_processing_leases.expires_at
                         <= CAST(strftime('%s', 'now') AS INTEGER)""",
                (session_id, purpose, owner_id, ttl_seconds),
            ).rowcount
        return bool(changed)

    def release_lease(self, session_id: str, *, purpose: str,
                      owner_id: str) -> None:
        with self._connections.connect() as connection:
            connection.execute(
                """DELETE FROM memory_processing_leases
                   WHERE session_id = ? AND purpose = ? AND owner_id = ?""",
                (session_id, purpose, owner_id),
            )

    def list_messages_after(self, session_id: str, *, after_message_id: int,
                            limit: int) -> tuple[SessionMessage, ...]:
        with self._connections.connect() as connection:
            rows = connection.execute(
                """SELECT m.message_id, m.role, m.content, m.created_at,
                          c.origin_type, c.origin_client
                   FROM messages m
                   JOIN conversations c ON c.session_id = m.session_id
                   WHERE m.session_id = ? AND m.message_id > ?
                   ORDER BY m.message_id LIMIT ?""",
                (session_id, after_message_id, limit),
            ).fetchall()
        return tuple(SessionMessage(
                         int(row["message_id"]), str(row["role"]),
                         str(row["content"]), str(row["created_at"]),
                         str(row["origin_type"]), str(row["origin_client"]),
                     )
                     for row in rows)

    def pending_messages(self, session_id: str, *, limit: int = 20) -> tuple[SessionMessage, ...]:
        memory = self.get_context_snapshot(session_id, recent_message_limit=1)
        return self.list_messages_after(
            session_id, after_message_id=memory.distilled_until_message_id, limit=limit
        )

    def update_summary(self, session_id: str, *, summary: str,
                       summary_until_message_id: int) -> None:
        with self._connections.connect() as connection:
            connection.execute(
                """UPDATE conversations SET summary = ?, summary_until_message_id = ?,
                          updated_at = datetime('now') WHERE session_id = ?""",
                (summary, summary_until_message_id, session_id),
            )

    def update_active_context(self, session_id: str,
                              context: ActiveTaskContext) -> None:
        payload = json.dumps({
            "active_goal": context.active_goal,
            "completed_steps": list(context.completed_steps),
            "pending_steps": list(context.pending_steps),
            "artifact_ids": list(context.artifact_ids),
        }, ensure_ascii=False)
        with self._connections.connect() as connection:
            connection.execute(
                "UPDATE conversations SET active_context_json = ? WHERE session_id = ?",
                (payload, session_id),
            )

    def update_distillation_cursor(self, session_id: str, *,
                                   message_id: int | None = None,
                                   distilled_until_message_id: int | None = None) -> None:
        cursor = message_id if message_id is not None else distilled_until_message_id
        if cursor is None:
            raise ValueError("必须提供长期记忆蒸馏游标")
        with self._connections.connect() as connection:
            connection.execute(
                """UPDATE conversations SET distilled_until_message_id = ?,
                          updated_at = datetime('now') WHERE session_id = ?""",
                (cursor, session_id),
            )

    def list_internal_sessions(self, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        """按最近更新时间列出网页内部会话，并用首条用户消息生成展示标题。"""

        actual_limit = min(max(int(limit), 1), 100)
        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.session_id,
                       COALESCE(NULLIF(c.title, ''), (
                           SELECT substr(m.content, 1, 48)
                           FROM messages m
                           WHERE m.session_id = c.session_id AND m.role = 'user'
                           ORDER BY m.message_id LIMIT 1
                       ), '新对话') AS title,
                       c.message_count, c.created_at, c.updated_at
                FROM conversations c
                WHERE c.origin_type = 'internal'
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (actual_limit,),
            ).fetchall()
        return tuple({
            "session_id": str(row["session_id"]),
            "title": str(row["title"]),
            "message_count": int(row["message_count"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        } for row in rows)

    def list_session_messages(
        self, session_id: str, *, limit: int = 500,
    ) -> tuple[SessionMessage, ...]:
        """只读取内部会话消息，避免网页访问外部 Hook/MCP 会话。"""

        actual_limit = min(max(int(limit), 1), 1000)
        with self._connections.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.message_id, m.role, m.content, m.created_at,
                       c.origin_type, c.origin_client
                FROM messages m
                JOIN conversations c ON c.session_id = m.session_id
                WHERE m.session_id = ? AND c.origin_type = 'internal'
                ORDER BY m.message_id LIMIT ?
                """,
                (session_id, actual_limit),
            ).fetchall()
        return tuple(SessionMessage(
            message_id=int(row["message_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            origin_type=str(row["origin_type"]),
            origin_client=str(row["origin_client"]),
        ) for row in rows)

    def delete_internal_session(self, session_id: str) -> bool:
        """删除内部会话及 FTS 副本，外部会话和长期记忆不受影响。"""

        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT session_id FROM conversations WHERE session_id = ? AND origin_type = 'internal'",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM messages_fts WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
        return True

    def rename_session(self, session_id: str, *, title: str) -> bool:
        """重命名任意来源会话；只修改本地展示标题，不改写外部智能体文件。"""

        normalized_title = title.strip()[:120]
        if not normalized_title:
            raise ValueError("会话名称不能为空")
        with self._connections.connect() as connection:
            row = connection.execute(
                "SELECT title, source_metadata_json FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            try:
                metadata = json.loads(str(row["source_metadata_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            metadata["manual_title"] = normalized_title
            # A verified external-agent title remains authoritative when available.
            displayed_title = str(metadata.get("external_title") or "").strip() or normalized_title
            cursor = connection.execute(
                """UPDATE conversations
                   SET title = ?, source_metadata_json = ?, updated_at = datetime('now')
                   WHERE session_id = ?""",
                (displayed_title, json.dumps(metadata, ensure_ascii=False), session_id),
            )
        return cursor.rowcount > 0

    def delete_session_with_memories(self, session_id: str) -> dict[str, int] | None:
        """删除本地会话投影及由该会话产生的记忆点和记忆关系。"""

        with self._connections.connect() as connection:
            session = connection.execute(
                "SELECT session_id FROM conversations WHERE session_id = ?", (session_id,),
            ).fetchone()
            if session is None:
                return None
            memory_rows = connection.execute(
                "SELECT DISTINCT memory_id FROM memory_sources WHERE session_id = ?", (session_id,),
            ).fetchall()
            memory_ids = [str(row["memory_id"]) for row in memory_rows]
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                connection.execute(
                    f"DELETE FROM memory_relations WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                    [*memory_ids, *memory_ids],
                )
                connection.execute(
                    f"DELETE FROM memory_points_fts WHERE memory_id IN ({placeholders})", memory_ids,
                )
                connection.execute(
                    f"DELETE FROM memory_points WHERE memory_id IN ({placeholders})", memory_ids,
                )
            connection.execute("DELETE FROM messages_fts WHERE session_id = ?", (session_id,))
            cursor = connection.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
        return {"sessions": cursor.rowcount, "memories": len(memory_ids)}

    def delete_turn_with_memories(self, turn_id: str) -> dict[str, int] | None:
        """删除单轮对话、两条原始消息，以及该轮产生的记忆与关系。"""

        with self._connections.connect() as connection:
            turn = connection.execute(
                "SELECT session_id, user_message_id, assistant_message_id FROM conversation_turns WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
            if turn is None:
                return None
            memory_rows = connection.execute(
                "SELECT DISTINCT memory_id FROM memory_sources WHERE turn_id = ?", (turn_id,),
            ).fetchall()
            memory_ids = [str(row["memory_id"]) for row in memory_rows]
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                connection.execute(
                    f"DELETE FROM memory_relations WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                    [*memory_ids, *memory_ids],
                )
                connection.execute(f"DELETE FROM memory_points_fts WHERE memory_id IN ({placeholders})", memory_ids)
                connection.execute(f"DELETE FROM memory_points WHERE memory_id IN ({placeholders})", memory_ids)
            message_ids = [int(turn["user_message_id"]), int(turn["assistant_message_id"])]
            connection.execute("DELETE FROM messages_fts WHERE message_id IN (?, ?)", message_ids)
            connection.execute("DELETE FROM conversation_turns WHERE turn_id = ?", (turn_id,))
            connection.execute("DELETE FROM messages WHERE message_id IN (?, ?)", message_ids)
            connection.execute(
                "UPDATE conversations SET message_count = MAX(0, message_count - 2), updated_at = datetime('now') WHERE session_id = ?",
                (str(turn["session_id"]),),
            )
        return {"turns": 1, "messages": 2, "memories": len(memory_ids)}
    def create_internal_session(
        self, session_id: str, *, title: str = "新对话",
    ) -> dict[str, Any]:
        """幂等创建网页内部会话；创建本身不伪造任何消息。"""

        normalized_id = session_id.strip()
        if not normalized_id:
            raise ValueError("session_id 不能为空")
        normalized_title = title.strip() or "新对话"
        with self._connections.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations
                       (session_id, title, message_count, created_at, updated_at,
                        origin_type, origin_client, source_metadata_json)
                VALUES (?, ?, 0, datetime('now'), datetime('now'),
                        'internal', 'personal_agent', '{}')
                ON CONFLICT(session_id) DO NOTHING
                """,
                (normalized_id, normalized_title),
            )
            row = connection.execute(
                """SELECT session_id, title, message_count, created_at, updated_at
                   FROM conversations
                   WHERE session_id = ? AND origin_type = 'internal'""",
                (normalized_id,),
            ).fetchone()
        if row is None:
            raise ValueError("session_id 已被非内部会话占用")
        return {
            "session_id": str(row["session_id"]),
            "title": str(row["title"] or "新对话"),
            "message_count": int(row["message_count"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

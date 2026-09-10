"""短期会话记忆相关数据库迁移。"""

import sqlite3

from study_help_agent.infrastructure.persistence.migrations import Migration


def migration_012_add_conversation_context_fields(
    connection: sqlite3.Connection,
) -> None:
    """给 conversations 增加摘要、任务上下文和蒸馏进度。"""

    connection.executescript(
        """
        ALTER TABLE conversations
        ADD COLUMN summary TEXT NOT NULL DEFAULT '';

        ALTER TABLE conversations
        ADD COLUMN summary_until_message_id INTEGER NOT NULL DEFAULT 0;

        ALTER TABLE conversations
        ADD COLUMN distilled_until_message_id INTEGER NOT NULL DEFAULT 0;

        ALTER TABLE conversations
        ADD COLUMN active_context_json TEXT NOT NULL DEFAULT '{}';
        """
    )


CONVERSATION_CONTEXT_MIGRATIONS = [
    Migration(
        version=12,
        name="add session memory and consolidation cursors",
        upgrade=migration_012_add_conversation_context_fields,
    ),
    Migration(
        version=13,
        name="add idempotent turns and memory processing leases",
        upgrade=lambda connection: connection.executescript(
            """
            CREATE TABLE conversation_turns (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_message_id INTEGER NOT NULL,
                assistant_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE,
                FOREIGN KEY (user_message_id) REFERENCES messages(message_id) ON DELETE CASCADE,
                FOREIGN KEY (assistant_message_id) REFERENCES messages(message_id) ON DELETE CASCADE
            );
            CREATE INDEX idx_turns_session ON conversation_turns(session_id, created_at);

            CREATE TABLE memory_processing_leases (
                session_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (session_id, purpose)
            );
            """
        ),
    ),
    Migration(
        version=17,
        name="add distilled presentation fields to conversation turns",
        upgrade=lambda connection: connection.executescript(
            """
            ALTER TABLE conversation_turns
            ADD COLUMN conversation_title TEXT NOT NULL DEFAULT '';
            ALTER TABLE conversation_turns
            ADD COLUMN display_summary TEXT NOT NULL DEFAULT '';
            """
        ),
    ),
]

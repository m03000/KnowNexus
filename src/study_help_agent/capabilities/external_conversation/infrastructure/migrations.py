"""外部智能体来源与可追溯元数据的 SQLite 迁移。"""

import sqlite3

from study_help_agent.infrastructure.persistence.migrations import Migration


def migration_014_add_external_conversation_origin(connection: sqlite3.Connection) -> None:
    """为会话、轮次和蒸馏记忆增加来源，并建立外部 ID 唯一约束。"""

    connection.executescript(
        """
        ALTER TABLE conversations ADD COLUMN origin_type TEXT NOT NULL DEFAULT 'internal';
        ALTER TABLE conversations ADD COLUMN origin_client TEXT NOT NULL DEFAULT 'personal_agent';
        ALTER TABLE conversations ADD COLUMN external_session_id TEXT;
        ALTER TABLE conversations ADD COLUMN source_metadata_json TEXT NOT NULL DEFAULT '{}';

        ALTER TABLE conversation_turns ADD COLUMN origin_type TEXT NOT NULL DEFAULT 'internal';
        ALTER TABLE conversation_turns ADD COLUMN origin_client TEXT NOT NULL DEFAULT 'personal_agent';
        ALTER TABLE conversation_turns ADD COLUMN external_turn_id TEXT;
        ALTER TABLE conversation_turns ADD COLUMN source_metadata_json TEXT NOT NULL DEFAULT '{}';

        ALTER TABLE memories ADD COLUMN origin_type TEXT NOT NULL DEFAULT 'internal';
        ALTER TABLE memories ADD COLUMN origin_client TEXT NOT NULL DEFAULT 'personal_agent';

        CREATE UNIQUE INDEX idx_conversations_external_source
        ON conversations(origin_client, external_session_id)
        WHERE external_session_id IS NOT NULL;

        CREATE UNIQUE INDEX idx_turns_external_source
        ON conversation_turns(session_id, origin_client, external_turn_id)
        WHERE external_turn_id IS NOT NULL;
        """
    )


EXTERNAL_CONVERSATION_MIGRATIONS = [
    Migration(
        version=14,
        name="add external conversation and memory origin metadata",
        upgrade=migration_014_add_external_conversation_origin,
    )
]

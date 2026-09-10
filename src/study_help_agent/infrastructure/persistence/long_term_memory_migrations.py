"""对话记忆表迁移。"""
import json
import sqlite3
from study_help_agent.infrastructure.persistence.migrations import Migration


def migration_010_create_conversation_tables(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    CREATE TABLE conversations (
        session_id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        message_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE
    );
    CREATE INDEX idx_msg_session ON messages(session_id);
    CREATE INDEX idx_msg_created ON messages(created_at);

    CREATE VIRTUAL TABLE messages_fts USING fts5(
        message_id UNINDEXED,
        session_id UNINDEXED,
        role UNINDEXED,
        content,
        tokenize='unicode61'
    );
    """)

def migration_011_create_memory_tables(connection: sqlite3.Connection) -> None:
    """记忆点表：蒸馏后的长期记忆。只存元数据，向量在 Qdrant user_memory。"""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            memory_id          TEXT PRIMARY KEY,          -- sha256(content+source_ids)
            content            TEXT NOT NULL,             -- 记忆原话（第一人称陈述）
            summary            TEXT NOT NULL DEFAULT '',  -- 图谱节点展示用摘要
            memory_type        TEXT NOT NULL DEFAULT 'fact',
            importance         INTEGER NOT NULL DEFAULT 3,
            source_message_ids TEXT NOT NULL DEFAULT '[]',  -- JSON 数组，溯源外键
            topics             TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
            created_at         TEXT NOT NULL,
            last_accessed_at   TEXT NOT NULL,
            access_count       INTEGER NOT NULL DEFAULT 0,
            status             TEXT NOT NULL DEFAULT 'active'
        );
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_status_created "
        "ON memories(status, created_at DESC);"
    )


def migration_018_create_memory_graph_tables(connection: sqlite3.Connection) -> None:
    """将旧 memories 数据迁移为规范记忆点，并建立实体、来源和关系图。"""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_points (
            memory_id          TEXT PRIMARY KEY,
            user_id            TEXT NOT NULL DEFAULT 'default',
            content            TEXT NOT NULL,
            summary            TEXT NOT NULL DEFAULT '',
            memory_type        TEXT NOT NULL DEFAULT 'fact',
            subject            TEXT NOT NULL DEFAULT 'user',
            topic              TEXT NOT NULL DEFAULT '',
            importance         INTEGER NOT NULL DEFAULT 3,
            confidence         REAL NOT NULL DEFAULT 0.8,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            last_accessed_at   TEXT NOT NULL,
            access_count       INTEGER NOT NULL DEFAULT 0,
            status             TEXT NOT NULL DEFAULT 'active',
            origin_type        TEXT NOT NULL DEFAULT 'internal',
            origin_client      TEXT NOT NULL DEFAULT 'personal_agent'
        );

        CREATE INDEX IF NOT EXISTS idx_memory_points_status_created
            ON memory_points(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_memory_points_topic_type
            ON memory_points(topic, memory_type, status);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_points_fts USING fts5(
            memory_id UNINDEXED,
            content,
            summary,
            topic,
            tokenize='unicode61'
        );

        CREATE TABLE IF NOT EXISTS memory_entities (
            entity_id          TEXT PRIMARY KEY,
            user_id            TEXT NOT NULL DEFAULT 'default',
            name               TEXT NOT NULL,
            normalized_name    TEXT NOT NULL,
            entity_type        TEXT NOT NULL,
            created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, normalized_name, entity_type)
        );

        CREATE TABLE IF NOT EXISTS memory_sources (
            memory_id          TEXT NOT NULL,
            session_id         TEXT NOT NULL,
            turn_id            TEXT NOT NULL,
            message_id         INTEGER NOT NULL,
            created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(memory_id, message_id),
            FOREIGN KEY(memory_id) REFERENCES memory_points(memory_id)
                ON DELETE CASCADE,
            FOREIGN KEY(message_id) REFERENCES messages(message_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_memory_sources_turn
            ON memory_sources(turn_id, session_id);

        CREATE TABLE IF NOT EXISTS memory_relations (
            relation_id        TEXT PRIMARY KEY,
            source_type        TEXT NOT NULL,
            source_id          TEXT NOT NULL,
            target_type        TEXT NOT NULL,
            target_id          TEXT NOT NULL,
            relation_type      TEXT NOT NULL,
            confidence         REAL NOT NULL DEFAULT 0.8,
            created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_type, source_id, target_type, target_id, relation_type)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_relations_source
            ON memory_relations(source_type, source_id, relation_type);
        CREATE INDEX IF NOT EXISTS idx_memory_relations_target
            ON memory_relations(target_type, target_id, relation_type);
        """
    )

    # 兼容已有数据库：旧 memories 仍保留，只迁移一次作为回滚保障。
    old_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()
    if old_exists:
        rows = connection.execute("SELECT * FROM memories").fetchall()
        for row in rows:
            topics = str(row["topics"] or "[]")
            try:
                topic_values = json.loads(topics)
                topic = str(topic_values[0]) if topic_values else ""
            except (TypeError, ValueError):
                topic = ""
            connection.execute(
                """
                INSERT OR IGNORE INTO memory_points (
                    memory_id, content, summary, memory_type, topic, importance,
                    created_at, updated_at, last_accessed_at, access_count, status,
                    origin_type, origin_client
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["memory_id"], row["content"], row["summary"],
                    row["memory_type"], topic, row["importance"], row["created_at"],
                    row["last_accessed_at"], row["last_accessed_at"],
                    row["access_count"], row["status"],
                    row["origin_type"] if "origin_type" in row.keys() else "internal",
                    row["origin_client"] if "origin_client" in row.keys() else "personal_agent",
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO memory_points_fts(memory_id, content, summary, topic) "
                "VALUES (?, ?, ?, ?)",
                (row["memory_id"], row["content"], row["summary"], topic),
            )
            try:
                source_ids = json.loads(str(row["source_message_ids"] or "[]"))
            except (TypeError, ValueError):
                source_ids = []
            for message_id in source_ids:
                source = connection.execute(
                    """SELECT m.session_id, COALESCE(t.turn_id, '') AS turn_id
                       FROM messages m LEFT JOIN conversation_turns t
                         ON t.user_message_id=m.message_id OR t.assistant_message_id=m.message_id
                       WHERE m.message_id=? LIMIT 1""",
                    (message_id,),
                ).fetchone()
                if source:
                    connection.execute(
                        "INSERT OR IGNORE INTO memory_sources"
                        "(memory_id, session_id, turn_id, message_id) VALUES (?, ?, ?, ?)",
                        (row["memory_id"], source["session_id"], source["turn_id"], message_id),
                    )

CONVERSATION_MIGRATIONS = [
    Migration(
        version=10,
        name="create conversation and message tables with FTS5 index",
        upgrade=migration_010_create_conversation_tables,
    ),
    Migration(
        version=11,
        name="create memories table",
        upgrade=migration_011_create_memory_tables,
    ),
    Migration(
        version=18,
        name="create normalized memory point entity source and relation graph",
        upgrade=migration_018_create_memory_graph_tables,
    ),
]

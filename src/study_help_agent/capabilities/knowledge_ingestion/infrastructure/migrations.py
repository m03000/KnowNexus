"""知识资产与 Transactional Outbox 的数据库迁移。"""

import sqlite3

from study_help_agent.infrastructure.persistence.migrations import Migration


def migration_007_create_knowledge_ingestion(connection: sqlite3.Connection) -> None:
    """创建规范资产表和可靠入库任务表；Chunk 表留到第三阶段。"""

    connection.executescript(
        """
        CREATE TABLE knowledge_assets (
            asset_id TEXT PRIMARY KEY,
            space TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            stable_source_key TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (space, stable_source_key)
        );

        CREATE INDEX idx_knowledge_assets_space_type
        ON knowledge_assets (space, asset_type);

        CREATE INDEX idx_knowledge_assets_status
        ON knowledge_assets (status);

        CREATE TABLE ingestion_outbox (
            job_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            asset_version INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES knowledge_assets(asset_id)
                ON DELETE CASCADE,
            UNIQUE (asset_id, asset_version, event_type)
        );

        CREATE INDEX idx_ingestion_outbox_claim
        ON ingestion_outbox (status, next_retry_at, created_at);
        """
    )


KNOWLEDGE_INGESTION_MIGRATIONS = [
    Migration(
        version=7,
        name="create knowledge assets and ingestion outbox",
        upgrade=migration_007_create_knowledge_ingestion,
    ),
    Migration(
        version=8,
        name="create knowledge chunks and lexical index",
        upgrade=lambda connection: connection.executescript(
            """
            CREATE TABLE knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                asset_version INTEGER NOT NULL,
                space TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                logical_key TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES knowledge_assets(asset_id)
                    ON DELETE CASCADE,
                UNIQUE (asset_id, asset_version, logical_key)
            );

            CREATE INDEX idx_knowledge_chunks_asset
            ON knowledge_chunks (asset_id, asset_version, chunk_index);

            CREATE INDEX idx_knowledge_chunks_space
            ON knowledge_chunks (space);

            CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                asset_id UNINDEXED,
                space UNINDEXED,
                title,
                content,
                tokenize='unicode61'
            );
            """
        ),
    ),
]

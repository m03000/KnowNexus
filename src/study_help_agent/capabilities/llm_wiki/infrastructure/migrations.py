"""LLM Wiki 的来源、页面、引用和增量构建表。"""

import sqlite3

from study_help_agent.infrastructure.persistence.migrations import Migration


def migration_020_create_llm_wiki(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE wiki_sources (
            source_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            original_path TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            media_type TEXT NOT NULL DEFAULT 'text/markdown',
            normalized_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'deleted', 'failed')),
            version INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_wiki_sources_kind ON wiki_sources(source_kind);
        CREATE INDEX idx_wiki_sources_status ON wiki_sources(status);

        CREATE TABLE wiki_pages (
            page_id TEXT PRIMARY KEY,
            page_type TEXT NOT NULL
                CHECK (page_type IN ('concept', 'topic', 'synthesis', 'source')),
            canonical_title TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            summary TEXT NOT NULL DEFAULT '',
            body_markdown TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'active', 'archived', 'failed')),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_wiki_pages_type ON wiki_pages(page_type);
        CREATE INDEX idx_wiki_pages_status ON wiki_pages(status);

        CREATE TABLE wiki_page_sources (
            page_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            segment_key TEXT NOT NULL,
            locator TEXT NOT NULL DEFAULT '',
            evidence_excerpt TEXT NOT NULL DEFAULT '',
            contribution_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (page_id, source_id, segment_key),
            FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES wiki_sources(source_id) ON DELETE CASCADE
        );
        CREATE INDEX idx_wiki_page_sources_source ON wiki_page_sources(source_id);

        CREATE TABLE wiki_links (
            source_page_id TEXT NOT NULL,
            target_page_id TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'related',
            anchor_text TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (source_page_id, target_page_id, relation_type),
            FOREIGN KEY (source_page_id) REFERENCES wiki_pages(page_id) ON DELETE CASCADE,
            FOREIGN KEY (target_page_id) REFERENCES wiki_pages(page_id) ON DELETE CASCADE
        );
        CREATE INDEX idx_wiki_links_target ON wiki_links(target_page_id);

        CREATE TABLE wiki_aliases (
            alias_normalized TEXT PRIMARY KEY,
            alias TEXT NOT NULL,
            page_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id) ON DELETE CASCADE
        );
        CREATE INDEX idx_wiki_aliases_page ON wiki_aliases(page_id);

        CREATE TABLE wiki_builds (
            build_id TEXT PRIMARY KEY,
            trigger_kind TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('queued', 'running', 'completed', 'failed')),
            source_ids_json TEXT NOT NULL DEFAULT '[]',
            model_name TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX idx_wiki_builds_status ON wiki_builds(status);

        CREATE TABLE wiki_build_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            operation TEXT NOT NULL CHECK (operation IN ('upsert', 'delete')),
            source_version INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            scheduled_at TEXT NOT NULL DEFAULT (datetime('now')),
            started_at TEXT,
            finished_at TEXT,
            FOREIGN KEY (source_id) REFERENCES wiki_sources(source_id) ON DELETE CASCADE,
            UNIQUE (source_id, operation, source_version)
        );
        CREATE INDEX idx_wiki_build_queue_status
            ON wiki_build_queue(status, scheduled_at, queue_id);
        """
    )


def migration_021_create_wiki_page_fts(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE VIRTUAL TABLE wiki_pages_fts USING fts5(
            page_id UNINDEXED,
            canonical_title,
            summary,
            body_markdown,
            tokenize = 'unicode61'
        );
        """
    )


def migration_022_create_wiki_page_versions(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        ALTER TABLE wiki_pages ADD COLUMN topic_key TEXT NOT NULL DEFAULT '';
        CREATE TABLE wiki_page_versions (
            page_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            page_type TEXT NOT NULL,
            slug TEXT NOT NULL,
            canonical_title TEXT NOT NULL,
            topic_key TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            body_markdown TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (page_id, version)
        );
        CREATE INDEX idx_wiki_page_versions_page
            ON wiki_page_versions(page_id, version DESC);
        """
    )


LLM_WIKI_MIGRATIONS = [
    Migration(
        version=20,
        name="create llm wiki source page and build tables",
        upgrade=migration_020_create_llm_wiki,
    ),
    Migration(
        version=21,
        name="create llm wiki page full text index",
        upgrade=migration_021_create_wiki_page_fts,
    ),
    Migration(
        version=22,
        name="create llm wiki page version snapshots",
        upgrade=migration_022_create_wiki_page_versions,
    ),
]

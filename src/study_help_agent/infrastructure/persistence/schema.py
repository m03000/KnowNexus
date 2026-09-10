""" 数据库 Schema 迁移清单。"""

import sqlite3

from study_help_agent.infrastructure.persistence.migrations import (
    Migration,
)
from study_help_agent.capabilities.code_analysis.infrastructure.migrations import (
    CODE_ANALYSIS_MIGRATIONS,
)
from study_help_agent.capabilities.knowledge_ingestion.infrastructure.migrations import (
    KNOWLEDGE_INGESTION_MIGRATIONS,
)
from study_help_agent.capabilities.learning_notes.infrastructure.migrations import (
    NOTE_POINT_MIGRATIONS,
)
from .long_term_memory_migrations import (
    CONVERSATION_MIGRATIONS,
)
from study_help_agent.capabilities.conversation_context.infrastructure.migrations import (
    CONVERSATION_CONTEXT_MIGRATIONS,
)
from study_help_agent.capabilities.external_conversation.infrastructure.migrations import (
    EXTERNAL_CONVERSATION_MIGRATIONS,
)
from study_help_agent.capabilities.llm_wiki.infrastructure.migrations import (
    LLM_WIKI_MIGRATIONS,
)

def migration_001_create_app_metadata(
    connection: sqlite3.Connection,
) -> None:
    """创建应用元数据表。"""

    connection.execute(
        """
        CREATE TABLE app_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def migration_023_create_watcher_monitor_tables(connection: sqlite3.Connection) -> None:
    """保存外部智能体监听的低频汇总数据，支持按时间范围统计。"""

    connection.executescript(
        """
        CREATE TABLE watcher_monitor_buckets (
            watcher_id TEXT NOT NULL,
            watcher_name TEXT NOT NULL,
            bucket_start TEXT NOT NULL,
            active_seconds INTEGER NOT NULL DEFAULT 0,
            captured_turns INTEGER NOT NULL DEFAULT 0,
            duplicate_turns INTEGER NOT NULL DEFAULT 0,
            estimated_tokens INTEGER NOT NULL DEFAULT 0,
            scan_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (watcher_id, bucket_start)
        );
        CREATE INDEX idx_watcher_monitor_bucket_time
            ON watcher_monitor_buckets(bucket_start);
        CREATE TABLE watcher_monitor_sessions (
            watcher_id TEXT NOT NULL,
            external_session_id TEXT NOT NULL,
            bucket_start TEXT NOT NULL,
            PRIMARY KEY (watcher_id, external_session_id, bucket_start)
        );
        CREATE INDEX idx_watcher_monitor_session_time
            ON watcher_monitor_sessions(bucket_start);
        """
    )


def migration_024_add_distillation_tokens(connection: sqlite3.Connection) -> None:
    """单独保存模型实际报告的蒸馏 token，避免沿用旧估算值。"""

    connection.execute(
        "ALTER TABLE watcher_monitor_buckets ADD COLUMN distillation_tokens INTEGER NOT NULL DEFAULT 0"
    )

def migration_025_create_daily_memory_summaries(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE daily_memory_summaries (
        summary_date TEXT NOT NULL, item_order INTEGER NOT NULL,
        title TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(summary_date,item_order))""")

def migration_026_create_research_hotspots(connection: sqlite3.Connection) -> None:
    connection.executescript("""CREATE TABLE research_topics (
        topic_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
    CREATE TABLE research_hotspot_slots (
        slot_id INTEGER PRIMARY KEY CHECK(slot_id BETWEEN 1 AND 3), topic_id INTEGER,
        FOREIGN KEY(topic_id) REFERENCES research_topics(topic_id));
    INSERT INTO research_hotspot_slots(slot_id) VALUES (1),(2),(3);
    CREATE TABLE research_hotspots (
        hotspot_id INTEGER PRIMARY KEY AUTOINCREMENT, slot_id INTEGER NOT NULL, topic_id INTEGER NOT NULL,
        research_date TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0, added_to_wiki INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
        UNIQUE(slot_id,research_date));""")


CORE_MIGRATIONS = [
    Migration(
        version=1,
        name="create app metadata",
        upgrade=migration_001_create_app_metadata,
    ),
    Migration(
        version=5,
        name="remove retired code review tables",
        upgrade=lambda connection: connection.executescript(
            """
            DROP TABLE IF EXISTS code_review_conclusions;
            DROP TABLE IF EXISTS code_review_issues;
            DROP TABLE IF EXISTS code_review_files;
            DROP TABLE IF EXISTS code_review_projects;
            """
        ),
    ),
    Migration(
        version=6,
        name="remove retired learning plan tables",
        upgrade=lambda connection: connection.executescript(
            """
            DROP TABLE IF EXISTS knowledge_subgraphs;
            DROP TABLE IF EXISTS personal_roadmaps;
            DROP TABLE IF EXISTS roadmap_tree;
            """
        ),
    ),
    Migration(
        version=23,
        name="create watcher monitor history",
        upgrade=migration_023_create_watcher_monitor_tables,
    ),
    Migration(
        version=24,
        name="add actual distillation token statistics",
        upgrade=migration_024_add_distillation_tokens,
    ),
    Migration(version=25, name="create daily memory summaries", upgrade=migration_025_create_daily_memory_summaries),
    Migration(version=26, name="create research hotspot workspace", upgrade=migration_026_create_research_hotspots),
]

# 每个模块在自己的 infrastructure/migrations.py 中声明自己需要的表。总汇总文件只负责"收集"。新模块加入时只需要在这里加一行，不需要修改迁移引擎本身。
MIGRATIONS = [
    *CORE_MIGRATIONS,
    *CODE_ANALYSIS_MIGRATIONS,
    *KNOWLEDGE_INGESTION_MIGRATIONS,
    *NOTE_POINT_MIGRATIONS,
    *CONVERSATION_MIGRATIONS,
    *CONVERSATION_CONTEXT_MIGRATIONS,
    *EXTERNAL_CONVERSATION_MIGRATIONS,
    *LLM_WIKI_MIGRATIONS,
]

"""代码解释模块的数据库迁移。

本文件只定义 code_analysis 模块拥有的表。
其他业务模块不能在这里创建或修改自己的表。
"""

import sqlite3

from study_help_agent.infrastructure.persistence.migrations import (
    Migration,
)


def migration_002_create_code_analysis_tables(
    connection: sqlite3.Connection,
) -> None:
    """创建代码解释模块的三张业务表。"""

    connection.execute(
        """
        CREATE TABLE code_explainer_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_name TEXT NOT NULL,
            project_path TEXT NOT NULL,
            fingerprint TEXT NOT NULL,

            status TEXT NOT NULL
                CHECK (
                    status IN (
                        'processing',
                        'completed',
                        'stale',
                        'failed'
                    )
                ),

            project_summary TEXT NOT NULL
                DEFAULT '',

            total_files INTEGER NOT NULL
                DEFAULT 0
                CHECK (total_files >= 0),

            total_blocks INTEGER NOT NULL
                DEFAULT 0
                CHECK (total_blocks >= 0),

            scanned_at TEXT NOT NULL
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE code_explainer_source_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER NOT NULL,

            file_path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            source_text TEXT NOT NULL,
            file_role TEXT NOT NULL DEFAULT '',

            FOREIGN KEY (project_id)
                REFERENCES code_explainer_projects(id)
                ON DELETE CASCADE,

            UNIQUE (
                project_id,
                file_path
            )
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE code_explainer_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,

            code_name TEXT NOT NULL,

            code_type TEXT NOT NULL
                CHECK (
                    code_type IN (
                        'module',
                        'class',
                        'function',
                        'method',
                        'block'
                    )
                ),

            parent_class TEXT NOT NULL DEFAULT '',

            line_start INTEGER NOT NULL
                CHECK (line_start >= 1),

            line_end INTEGER NOT NULL
                CHECK (line_end >= line_start),

            explanation TEXT NOT NULL,
            docstring TEXT NOT NULL DEFAULT '',
            full_code TEXT NOT NULL DEFAULT '',

            FOREIGN KEY (
                project_id,
                file_path
            )
                REFERENCES code_explainer_source_files (
                    project_id,
                    file_path
                )
                ON DELETE CASCADE
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX
        idx_code_explainer_project_cache
        ON code_explainer_projects (
            project_path,
            fingerprint,
            status
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX
        idx_code_explainer_files_project
        ON code_explainer_source_files (
            project_id
        )
        """
    )

    connection.execute(
        """
        CREATE INDEX
        idx_code_explainer_blocks_file
        ON code_explainer_blocks (
            project_id,
            file_path,
            line_start
        )
        """
    )


CODE_ANALYSIS_MIGRATIONS = [
    Migration(
        version=2,
        name="create code analysis tables",
        upgrade=migration_002_create_code_analysis_tables,
    ),
    Migration(
        version=15,
        name="add exact code analysis cache key",
        upgrade=lambda connection: connection.executescript(
            """
            ALTER TABLE code_explainer_projects
            ADD COLUMN analysis_fingerprint TEXT NOT NULL DEFAULT '';

            CREATE INDEX idx_code_explainer_exact_cache
            ON code_explainer_projects (
                project_path, fingerprint, analysis_fingerprint, status
            );
            """
        ),
    ),
]

"""轻量级 SQLite 数据库迁移器。"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


# Callable[[sqlite3.Connection], None] 表示："一个函数，接收 sqlite3.Connection 参数，返回 None"。
MigrationFunction = Callable[
    [sqlite3.Connection],
    None,
]


@dataclass(frozen=True, slots=True)
class Migration:
    """一条数据库迁移定义。"""

    version: int
    name: str
    upgrade: MigrationFunction


def create_migration_table(
    connection: sqlite3.Connection,
) -> None:
    """创建迁移历史表。"""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def get_applied_versions(
    connection: sqlite3.Connection,
) -> set[int]:
    """读取已经执行过的迁移版本。"""

    rows = connection.execute(
        """
        SELECT version
        FROM schema_migrations
        ORDER BY version
        """
    ).fetchall()

    return {
        int(row["version"])
        for row in rows
    }


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: list[Migration],
) -> None:
    """按版本顺序应用尚未执行的迁移。"""

    create_migration_table(connection)

    applied_versions = get_applied_versions(
        connection
    )

    ordered_migrations = sorted(
        migrations,
        key=lambda item: item.version,
    )

    seen_versions: set[int] = set()

    for migration in ordered_migrations:
        if migration.version in seen_versions:
            raise ValueError(
                "数据库迁移版本重复："
                f"{migration.version}"
            )

        seen_versions.add(migration.version)

        if migration.version in applied_versions:
            continue

        migration.upgrade(connection)

        connection.execute(
            """
            INSERT INTO schema_migrations (
                version,
                name
            )
            VALUES (?, ?)
            """,
            (
                migration.version,
                migration.name,
            ),
        )
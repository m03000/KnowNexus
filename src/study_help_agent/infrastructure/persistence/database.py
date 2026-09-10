"""新架构数据库初始化入口。"""

from study_help_agent.infrastructure.persistence.migrations import (
    apply_migrations,
)
from study_help_agent.infrastructure.persistence.schema import (
    MIGRATIONS,
)
from study_help_agent.infrastructure.persistence.sqlite import (
    SqliteConnectionFactory,
)


def initialize_database(
    connections: SqliteConnectionFactory,
) -> None:
    """初始化新架构数据库并执行迁移。"""

    with connections.connect() as connection:
        # WAL 模式允许读写并发：一个连接在写入时，其他连接可以同时读取。
        connection.execute(
            "PRAGMA journal_mode = WAL"
        )

        apply_migrations(
            connection,
            MIGRATIONS,
        )
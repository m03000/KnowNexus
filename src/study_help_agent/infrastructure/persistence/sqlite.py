"""SQLite 连接和事务管理。"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class SqliteConnectionFactory:
    """创建并管理短生命周期 SQLite 连接。

    每次调用 connect() 创建一个连接。
    成功退出上下文时提交；
    发生异常时回滚；
    最终始终关闭连接。
    """

    def __init__(
        self,
        database_path: Path,
        *,
        timeout_seconds: float = 30.0,
        busy_timeout_ms: int = 5000,
    ) -> None:
        # expanduser()：把 ~ 展开为用户主目录,resolve()：解析所有符号链接，返回绝对路径
        self._database_path = (
            database_path.expanduser().resolve()
        )
        self._timeout_seconds = timeout_seconds
        self._busy_timeout_ms = busy_timeout_ms

    @property
    def database_path(self) -> Path:
        """返回当前数据库的规范化绝对路径。"""

        return self._database_path

    #
    @contextmanager
    def connect(
        self,
    ) -> Iterator[sqlite3.Connection]:
        """创建一个带事务管理的数据库连接。"""

        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # 创建连接
        connection = sqlite3.connect(
            self._database_path,
            timeout=self._timeout_seconds,
        )

        # 设置行工厂
        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            f"PRAGMA busy_timeout = "
            f"{self._busy_timeout_ms}"
        )

        try:
            # 交出连接给使用方
            yield connection
        except Exception:
            # 回滚
            connection.rollback()
            raise
        else:
            # 成功提交
            connection.commit()
        finally:
            # 最后一定关闭连接
            connection.close()
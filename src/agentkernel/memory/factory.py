"""Runtime 存储工厂（ADR-001）。

DSN 规则：
- `mysql://` / `mysql+pymysql://` → MySQL 主存储
- `sqlite://`、`:memory:` 或本地路径 → SQLite 测试适配器
- 未传 DSN 时读取 `AGENTKERNEL_DB_URL`；**两者都没有时直接报错**（G-06：不再内置默认口令）。
  本地开发请 `cp .env.example .env` 并填 DSN，或显式 `--db sqlite:///:memory:`。
"""

from __future__ import annotations

import os
from pathlib import Path

from agentkernel.memory.base import RuntimeStore
from agentkernel.memory.sqlite_store import SQLiteStore
from agentkernel.utils import env

env.load_env()


def _is_mysql_dsn(dsn: str) -> bool:
    return dsn.startswith("mysql://") or dsn.startswith("mysql+pymysql://")


def create_runtime_store(dsn: str | None = None, *, auto_create: bool = True) -> RuntimeStore:
    """按 DSN 创建 Runtime 存储；没有 DSN 时报错，不使用内置默认口令。"""
    resolved = dsn or os.environ.get("AGENTKERNEL_DB_URL")
    if not resolved:
        raise RuntimeError(
            "缺少 Runtime 存储 DSN：请设置 AGENTKERNEL_DB_URL、传 --db，"
            "或使用 --db sqlite:///:memory:（见 .env.example）"
        )

    if _is_mysql_dsn(resolved):
        from agentkernel.memory.mysql_store import MySQLRuntimeStore

        store = MySQLRuntimeStore(resolved)
        if auto_create:
            store._ensure_tables()  # dev 兜底；生产路径使用 Alembic 迁移
        return store

    if resolved == ":memory:" or resolved.startswith("sqlite://"):
        path = (
            ":memory:"
            if resolved in (":memory:", "sqlite:///:memory:")
            else resolved.removeprefix("sqlite:///")
        )
        return SQLiteStore(path)

    # 裸路径：本地开发时兼容旧用法
    return SQLiteStore(Path(resolved).expanduser())

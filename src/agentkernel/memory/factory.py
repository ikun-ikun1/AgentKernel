"""Runtime 存储工厂（ADR-001）。

DSN 规则：
- `mysql://` / `mysql+pymysql://` → MySQL 主存储
- `sqlite://`、`:memory:` 或本地路径 → SQLite 测试适配器
- 未传 DSN 时读取 `AGENTKERNEL_DB_URL`；仍未设置则使用 MySQL 默认 DSN
  （与 docker-compose.yml 保持一致），连接失败时由调用方决定是否降级 SQLite。
"""
from __future__ import annotations

import os
from pathlib import Path

from agentkernel.memory.base import RuntimeStore
from agentkernel.memory.sqlite_store import SQLiteStore
from agentkernel.utils import env

env.load_env()

DEFAULT_MYSQL_DSN = "mysql+pymysql://agentkernel:agentkernel@127.0.0.1:3306/agentkernel"


def _is_mysql_dsn(dsn: str) -> bool:
    return dsn.startswith("mysql://") or dsn.startswith("mysql+pymysql://")


def create_runtime_store(dsn: str | None = None, *, auto_create: bool = True) -> RuntimeStore:
    """按 DSN 创建 Runtime 存储。"""
    resolved = dsn or os.environ.get("AGENTKERNEL_DB_URL") or DEFAULT_MYSQL_DSN

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

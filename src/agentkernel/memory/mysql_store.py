"""兼容 shim：MySQL 适配器已移到 adapters/memory/mysql_store.py（A2）。"""

from __future__ import annotations

from agentkernel.adapters.memory.mysql_store import MySQLRuntimeStore, MySQLStoreError

__all__ = ["MySQLRuntimeStore", "MySQLStoreError"]

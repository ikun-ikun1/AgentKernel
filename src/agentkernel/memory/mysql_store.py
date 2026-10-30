"""兼容 shim：MySQL 适配器已移到 adapters/memory/mysql_store.py（A2）。"""

from __future__ import annotations

from agentkernel._compat import warn_deprecated

warn_deprecated("agentkernel.memory.mysql_store", "agentkernel.adapters.memory.mysql_store")

from agentkernel.adapters.memory.mysql_store import MySQLRuntimeStore, MySQLStoreError

__all__ = ["MySQLRuntimeStore", "MySQLStoreError"]

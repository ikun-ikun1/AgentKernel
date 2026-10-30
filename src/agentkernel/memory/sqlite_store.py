"""兼容 shim：SQLite 适配器已移到 adapters/memory/sqlite_store.py（A2）。"""

from __future__ import annotations

from agentkernel._compat import warn_deprecated

warn_deprecated("agentkernel.memory.sqlite_store", "agentkernel.adapters.memory.sqlite_store")

from agentkernel.adapters.memory.sqlite_store import SQLiteStore

__all__ = ["SQLiteStore"]

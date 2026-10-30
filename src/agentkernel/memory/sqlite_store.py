"""兼容 shim：SQLite 适配器已移到 adapters/memory/sqlite_store.py（A2）。"""

from __future__ import annotations

from agentkernel.adapters.memory.sqlite_store import SQLiteStore

__all__ = ["SQLiteStore"]

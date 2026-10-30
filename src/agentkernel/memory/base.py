"""兼容 shim：RuntimeStore 已移到 ports/runtime_store.py（A2）。

保留一个版本供旧 import 使用；内部代码请改用 agentkernel.ports.runtime_store。
"""

from __future__ import annotations

from agentkernel.ports.runtime_store import RuntimeStore

__all__ = ["RuntimeStore"]

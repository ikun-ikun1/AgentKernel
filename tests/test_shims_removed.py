"""v0.4.0：旧 shim 已删除；旧 import 必须失败，canonical 路径正常。"""

from __future__ import annotations

import importlib
import subprocess
import sys
import warnings

import pytest

REMOVED = [
    "agentkernel.memory.base",
    "agentkernel.memory.mysql_store",
    "agentkernel.memory.sqlite_store",
    "agentkernel.runtime.llm",
    "agentkernel.rag.ingest",
    "agentkernel.rag.mysql_store",
    "agentkernel.mcp.framing",
    "agentkernel.mcp.client",
    "agentkernel.mcp.server",
]


@pytest.mark.parametrize("old", REMOVED)
def test_removed_import_fails(old: str) -> None:
    sys.modules.pop(old, None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(old)


def test_canonical_mcp_server_entrypoint() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agentkernel.mcp_server", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower()


def test_canonical_imports_do_not_warn() -> None:
    modules = [
        "agentkernel.ports.runtime_store",
        "agentkernel.adapters.memory.sqlite_store",
        "agentkernel.adapters.llm.openai_compatible",
        "agentkernel.rag.knowledge",
        "agentkernel.protocol.mcp_framing",
        "agentkernel.adapters.mcp.client",
        "agentkernel.adapters.mcp.knowledge_server",
    ]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for name in modules:
            importlib.import_module(name)
    assert not [w for w in caught if issubclass(w.category, DeprecationWarning)]

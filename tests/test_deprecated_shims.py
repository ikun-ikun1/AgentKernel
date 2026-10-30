"""v0.3.1：旧 import 路径仍可用，但必须发 DeprecationWarning；canonical 路径不告警。"""

from __future__ import annotations

import importlib
import subprocess
import sys
import warnings

import pytest

SHIMS = [
    ("agentkernel.memory.base", "agentkernel.ports.runtime_store"),
    ("agentkernel.memory.mysql_store", "agentkernel.adapters.memory.mysql_store"),
    ("agentkernel.memory.sqlite_store", "agentkernel.adapters.memory.sqlite_store"),
    ("agentkernel.runtime.llm", "agentkernel.adapters.llm.openai_compatible"),
    ("agentkernel.rag.ingest", "agentkernel.rag.knowledge"),
    ("agentkernel.rag.mysql_store", "agentkernel.adapters.knowledge.mysql_ngram"),
    ("agentkernel.mcp.framing", "agentkernel.protocol.mcp_framing"),
    ("agentkernel.mcp.client", "agentkernel.adapters.mcp.client"),
    ("agentkernel.mcp.server", "agentkernel.adapters.mcp.knowledge_server"),
]


@pytest.mark.parametrize(("old", "new"), SHIMS)
def test_old_import_warns_and_points_to_canonical(old: str, new: str) -> None:
    sys.modules.pop(old, None)
    with pytest.warns(DeprecationWarning, match="v0.4.0"):
        module = importlib.import_module(old)
    assert module is not None
    canonical = importlib.import_module(new)
    assert canonical is not None


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

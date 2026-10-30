"""G-06：禁止内置默认口令；缺 DSN 必须显式报错。"""

from __future__ import annotations

import pathlib

import pytest

from agentkernel.memory.factory import create_runtime_store
from agentkernel.memory.sqlite_store import SQLiteStore


def test_missing_dsn_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTKERNEL_DB_URL", raising=False)
    with pytest.raises(RuntimeError, match="AGENTKERNEL_DB_URL"):
        create_runtime_store()


def test_explicit_memory_dsn_works() -> None:
    store = create_runtime_store(":memory:")
    assert isinstance(store, SQLiteStore)
    store.close()


def test_no_hardcoded_default_password_in_repo() -> None:
    repo = pathlib.Path(__file__).resolve().parents[1]
    needle = "agentkernel" + ":" + "agentkernel"
    patterns = ("src/**/*.py", "migrations/**/*.py", "scripts/*.py", "alembic.ini")
    offenders = [
        str(path.relative_to(repo))
        for pattern in patterns
        for path in repo.glob(pattern)
        if needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == []

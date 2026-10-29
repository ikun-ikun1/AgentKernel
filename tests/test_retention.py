"""P0-4b：tool_logs 耗时列、保留期清理、prune 脚本。"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentkernel.memory.sqlite_store import SQLiteStore


def test_duration_roundtrip() -> None:
    store = SQLiteStore(":memory:")
    store.create_session("s")
    store.log_tool_call("s", "calculator", {"expression": "1+1"}, "2", True, duration_ms=12.5)
    logs = store.list_tool_logs("s")
    assert logs[0]["duration_ms"] == 12.5


def test_prune_before_removes_only_old_rows() -> None:
    store = SQLiteStore(":memory:")
    store.create_session("s")
    store.append_message("s", "user", "old")
    store.append_message("s", "user", "new")
    store.log_tool_call("s", "calculator", {}, "r", True, duration_ms=1.0)
    old = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    with store._conn:
        store._conn.execute("UPDATE messages SET created_at = ? WHERE content = 'old'", (old,))
        store._conn.execute("UPDATE tool_logs SET created_at = ?", (old,))

    counts = store.prune_before(90)

    assert counts == {"messages": 1, "tool_logs": 1}
    assert [m["content"] for m in store.get_messages("s")] == ["new"]


def test_prune_script_deletes_old_log_files(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    old_log = log_dir / "agentkernel.jsonl"
    old_log.write_text("{}\n", encoding="utf-8")
    old_ts = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(old_log, (old_ts, old_ts))
    fresh_log = log_dir / "fresh.jsonl"
    fresh_log.write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "prune.py"),
            "--log-dir",
            str(log_dir),
            "--log-days",
            "14",
            "--db-days",
            "90",
            "--dsn",
            ":memory:",
        ],
        check=True,
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert not old_log.exists()
    assert fresh_log.exists()
    assert "messages=" in result.stdout


def test_prune_rejects_negative_days() -> None:
    store = SQLiteStore(":memory:")
    try:
        store.prune_before(-1)
    except ValueError as exc:
        assert "负数" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应拒绝负数天数")

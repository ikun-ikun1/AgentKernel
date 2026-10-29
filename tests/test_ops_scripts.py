"""P0-4b：trace 视图与周报索引。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        check=True,
        cwd=repo,
        capture_output=True,
        text=True,
    )


def test_trace_script_renders_span_tree(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    log = tmp_path / "events.jsonl"
    events = [
        {
            "event": "turn",
            "ts": "2026-10-29T10:00:02+00:00",
            "trace_id": "abc123",
            "latency_ms": 10.0,
            "success": True,
            "span": {"id": "s1", "parent_id": None, "name": "turn"},
        },
        {
            "event": "tool",
            "ts": "2026-10-29T10:00:01+00:00",
            "trace_id": "abc123",
            "tool_name": "calculator",
            "latency_ms": 3.0,
            "success": True,
            "span": {"id": "s2", "parent_id": "s1", "name": "tool.calculator"},
        },
    ]
    log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    out = _run(repo, str(repo / "scripts" / "trace.py"), "--log", str(log), "--trace-id", "abc123")

    assert "trace abc123" in out.stdout
    assert "- turn [turn]" in out.stdout
    assert "  - tool.calculator [calculator]" in out.stdout
    assert "span=s2" in out.stdout


def test_report_index_keeps_one_row_per_week(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    log = tmp_path / "events.jsonl"
    log.write_text(
        json.dumps(
            {
                "event": "turn",
                "ts": "2026-10-29T10:00:00+00:00",
                "level": "INFO",
                "trace_id": "t1",
                "session_id_hash": "s1",
                "turn_id": "u1",
                "step": 1,
                "latency_ms": 100.0,
                "model": "deepseek-chat",
                "tokens": {"in": 10, "out": 5},
                "success": True,
                "error_type": None,
                "cost_usd": 0.0001,
                "span": {"id": "x", "parent_id": None, "name": "turn"},
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "reports"
    for week in ("2026-W44", "2026-W45", "2026-W44"):
        _run(
            repo,
            str(repo / "scripts" / "report.py"),
            "--log",
            str(log),
            "--out",
            str(out_dir),
            "--week",
            week,
        )

    index = (out_dir / "index.md").read_text(encoding="utf-8")
    rows = [line for line in index.splitlines() if line.startswith("| 2026-W")]
    assert len(rows) == 2
    assert any("2026-W45" in row for row in rows)

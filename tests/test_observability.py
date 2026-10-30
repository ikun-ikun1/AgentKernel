"""观测骨架测试（P0-4）：字段表、脱敏、成本、事件发出、审计失败可见。"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from agentkernel.adapters.memory.sqlite_store import SQLiteStore
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry
from agentkernel.utils import observability as obs
from tests.llm_client_stub import RuntimeLLMClient


@pytest.fixture(autouse=True)
def _reset_logging():
    obs.reset_for_tests()
    yield
    obs.reset_for_tests()


def _registry() -> Registry:
    registry = Registry()
    builtin.register_builtin(registry)
    return registry


def test_redact_masks_secrets() -> None:
    text = (
        "key=sk-abcdef123456 password=hunter2 "
        "mysql+pymysql://user:pw@127.0.0.1:3306/db Authorization: Bearer abc.def.ghi"
    )
    out = obs.redact(text)
    assert "sk-abcdef123456" not in out
    assert "hunter2" not in out
    assert "user:pw@" not in out
    assert "abc.def.ghi" not in out
    assert "***" in out


def test_truncate_marks_cut() -> None:
    out = obs.truncate("x" * (obs.MAX_FIELD_CHARS + 10))
    assert out.startswith("x" * obs.MAX_FIELD_CHARS)
    assert "truncated 10 chars" in out


def test_cost_known_and_unknown() -> None:
    usage = obs.Usage(1_000_000, 1_000_000)
    assert obs.cost_usd("deepseek-chat", usage) == pytest.approx(1.37)
    assert obs.cost_usd("mystery-model", usage) is None
    assert obs.cost_usd(None, usage) is None
    assert obs.cost_usd("deepseek-chat", None) is None


def test_unknown_model_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    obs.reset_pricing_warnings()
    with caplog.at_level(logging.WARNING, logger=obs.LOGGER_NAME):
        obs.cost_usd("mystery-model", obs.Usage(1, 1))
        obs.cost_usd("mystery-model", obs.Usage(1, 1))
    warned = [r for r in caplog.records if "pricing_unknown" in r.getMessage()]
    assert len(warned) == 1
    obs.reset_pricing_warnings()


def test_emit_writes_core_fields_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    obs.reset_for_tests()
    obs.configure(path=str(log))
    obs.emit(
        "turn",
        trace_id="t1",
        session_id_hash="s1",
        turn_id="u1",
        step=1,
        latency_ms=12.5,
        model="deepseek-chat",
        tokens={"in": 10, "out": 5},
        success=True,
        error_type=None,
        cost_usd=0.1,
        span={"id": "sp1", "parent_id": None, "name": "turn"},
        pricing_table_version=obs.PRICING_TABLE_VERSION,
    )
    obs.emit(
        "tool",
        trace_id="t1",
        session_id_hash="s1",
        turn_id="u1",
        step=1,
        latency_ms=3.0,
        model=None,
        tokens=None,
        success=True,
        error_type=None,
        tool_name="calculator",
        span={"id": "sp2", "parent_id": "sp1", "name": "tool.calculator"},
    )
    obs.reset_for_tests()
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    turn, tool = lines
    assert set(turn) == set(obs.CORE_FIELDS) | {"cost_usd", "span", "pricing_table_version"}
    assert set(tool) == set(obs.CORE_FIELDS) | {"tool_name", "span"}
    assert turn["tokens"] == {"in": 10, "out": 5}
    assert tool["tool_name"] == "calculator"


def test_agent_emits_turn_and_tool_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict] = []
    responses = [
        '{"action": "calculator", "action_input": {"expression": "1+1"}}',
        '{"action": "final_answer", "action_input": "2"}',
    ]
    monkeypatch.setattr(
        "agentkernel.adapters.llm.openai_compatible.chat", lambda messages: responses.pop(0)
    )
    agent = Agent(
        _registry(), llm_client=RuntimeLLMClient(), on_event=events.append, session_id="sess-1"
    )

    reply = agent.run("算一下 1+1", [])

    assert reply == "2"
    assert [e["event"] for e in events] == ["tool", "turn"]
    tool, turn = events
    assert tool["tool_name"] == "calculator"
    assert tool["success"] is True
    assert turn["step"] == 2
    assert turn["session_id_hash"] == obs.hash_session("sess-1")
    assert turn["tokens"] is None  # 假 LLM 没有 usage
    assert turn["cost_usd"] is None
    assert turn["trace_id"] == tool["trace_id"]
    assert turn["span"]["name"] == "turn"
    assert turn["span"]["parent_id"] is None
    assert tool["span"]["name"] == "tool.calculator"
    assert tool["span"]["parent_id"] == turn["span"]["id"]


def test_audit_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict] = []

    def boom(tool_name: str, action_input: dict, result: str) -> None:
        raise RuntimeError("audit down")

    responses = [
        '{"action": "calculator", "action_input": {"expression": "1+1"}}',
        '{"action": "final_answer", "action_input": "2"}',
    ]
    monkeypatch.setattr(
        "agentkernel.adapters.llm.openai_compatible.chat", lambda messages: responses.pop(0)
    )
    agent = Agent(
        _registry(), llm_client=RuntimeLLMClient(), on_event=events.append, on_tool_call=boom
    )

    agent.run("算一下", [])

    assert agent.audit_failures == 1
    assert any(e["event"] == "audit_failed" for e in events)


def test_store_redacts_tool_logs() -> None:
    store = SQLiteStore(":memory:")
    store.create_session("s")
    store.log_tool_call(
        "s",
        "calculator",
        {"api_key": "sk-abcdef123456"},
        "result password=hunter2",
        True,
    )
    logs = store.list_tool_logs("s")
    assert "sk-abcdef123456" not in str(logs[0]["input_json"])
    assert "hunter2" not in str(logs[0]["output_json"])
    assert "***" in str(logs[0]["input_json"])


def test_report_script_generates_weekly_markdown(tmp_path: Path) -> None:
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
                "latency_ms": 120.0,
                "model": "deepseek-chat",
                "tokens": {"in": 100, "out": 20},
                "success": True,
                "error_type": None,
                "cost_usd": 0.000049,
            }
        )
        + "\n{not json}\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "reports"
    subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "report.py"),
            "--log",
            str(log),
            "--out",
            str(out_dir),
            "--week",
            "2026-W44",
        ],
        check=True,
        cwd=repo,
        capture_output=True,
        text=True,
    )
    report = (out_dir / "2026-W44.md").read_text(encoding="utf-8")
    assert "S1" in report
    assert "解析失败行：1" in report
    assert "100" in report and "20" in report

"""CLI 入口：命令分发、文档入库、错误退出（补齐 __main__.py 覆盖）。"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

from agentkernel import __main__ as cli


def _run(monkeypatch: pytest.MonkeyPatch, inputs: list[str], argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["agentkernel", *argv])
    iterator = iter(inputs)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(iterator))
    cli.main()


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentkernel.adapters.llm.openai_compatible.chat",
        lambda messages, **kwargs: '{"action": "final_answer", "action_input": "ok"}',
    )


def test_redact_dsn_hides_password() -> None:
    out = cli._redact_dsn("mysql+pymysql://u:secret@127.0.0.1:3306/db")
    assert "secret" not in out
    assert ":***@" in out


def test_cli_command_dispatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _run(
        monkeypatch,
        [
            "/help",
            "/sessions",
            "/history",
            "/logs",
            "/docs",
            "/new demo",
            "/nope",
            "/ingest /no/such/path",
            "/quit",
        ],
        ["--db", "sqlite:///:memory:", "--kb-db", ":memory:"],
    )
    out = capsys.readouterr().out
    assert "内置命令" in out
    assert "已新建会话" in out
    assert "未知命令 /nope" in out
    assert "拒绝入库" in out or "路径不存在" in out


def test_cli_user_message_roundtrip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _run(
        monkeypatch,
        ["你好", "/history", "/quit"],
        ["--db", "sqlite:///:memory:", "--kb-db", ":memory:"],
    )
    out = capsys.readouterr().out
    assert "ok" in out
    assert "你 >" in out


def test_cli_ingests_docs_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("AGENTKERNEL_DOC_ROOTS", str(tmp_path))
    (tmp_path / "notes.md").write_text("ReAct 是 Reasoning + Acting。", encoding="utf-8")
    _run(
        monkeypatch,
        ["/docs", "/quit"],
        ["--db", "sqlite:///:memory:", "--kb-db", ":memory:", "--docs", str(tmp_path)],
    )
    out = capsys.readouterr().out
    assert "已入库 notes.md" in out
    assert "- notes.md" in out


def test_cli_migrate_requires_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.env_utils, "load_env", lambda: None)
    monkeypatch.delenv("AGENTKERNEL_DB_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["agentkernel", "--migrate"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_cli_unknown_mcp_profile_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    profiles = tmp_path / "mcp_profiles.toml"
    profiles.write_text("", encoding="utf-8")
    _run(
        monkeypatch,
        ["/quit"],
        [
            "--db",
            "sqlite:///:memory:",
            "--kb-db",
            ":memory:",
            "--mcp-profile",
            "nope",
            "--mcp-profiles-file",
            str(profiles),
        ],
    )
    assert "未声明的 MCP profile" in capsys.readouterr().out


def test_ingest_path_rejects_missing_and_unsupported(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentkernel.rag.ingest import KnowledgeBase

    monkeypatch.setenv("AGENTKERNEL_DOC_ROOTS", str(tmp_path))

    kb = KnowledgeBase(persist_dir=None)
    try:
        assert cli._ingest_path(kb, str(tmp_path / "missing.md")) == 0
        csv = tmp_path / "x.csv"
        csv.write_text("a,b", encoding="utf-8")
        assert cli._ingest_path(kb, str(csv)) == 0
    finally:
        kb.close()
    out = capsys.readouterr().out
    assert "路径不存在" in out or "拒绝入库" in out
    assert "入库失败" in out

"""P0-1：有副作用工具 + 人工审批 + 审计 + 单进程幂等。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentkernel.application.tool_executor import (
    ApprovalRequest,
    IdempotencyCache,
    idempotency_key,
    run_tool,
)
from agentkernel.cli.approval import ConsoleApproval
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry, Tool


class _ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls += 1
        return self.responses.pop(0)

    def pop_usage(self) -> None:
        return None

    def last_model(self) -> str | None:
        return None


def _write_registry(tmp_path: Path) -> Registry:
    registry = Registry()
    builtin.register_builtin(registry, workspace_root=tmp_path / "workspace")
    return registry


def _write_call(path: str, content: str = "hello", key: str | None = None) -> Any:
    args: dict[str, Any] = {"path": path, "content": content}
    if key is not None:
        args["idempotency_key"] = key
    from agentkernel.tools import contracts

    return contracts.ToolCall("write_workspace_file", args)


def _request(tool: str = "write_workspace_file") -> ApprovalRequest:
    return ApprovalRequest(
        tool_name=tool, arguments={"path": "a.txt"}, summary="path=a.txt", session_id="s"
    )


def test_tool_defaults_and_write_tool_flag(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    assert registry.get("calculator").requires_approval is False
    assert registry.get("write_workspace_file").requires_approval is True


def test_non_approval_tool_does_not_prompt() -> None:
    registry = Registry()
    registry.register(
        Tool(
            name="noop",
            description="noop",
            parameters={"type": "object", "properties": {}},
            fn=lambda args: "ok",
        )
    )
    called: list[str] = []

    def deny(_: ApprovalRequest) -> bool:
        called.append("prompted")
        return False

    from agentkernel.tools import contracts

    result = run_tool(registry, contracts.ToolCall("noop", {}), approval_fn=deny)
    assert str(result) == "ok"
    assert called == []


def test_approved_write_executes(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    requests: list[ApprovalRequest] = []

    def approve(request: ApprovalRequest) -> bool:
        requests.append(request)
        return True

    result = run_tool(
        registry, _write_call("notes/a.txt", "hello"), approval_fn=approve, session_id="s"
    )
    assert result.success is True
    assert result.approval_decision == "approved"
    assert requests and requests[0].tool_name == "write_workspace_file"
    assert (tmp_path / "workspace" / "notes" / "a.txt").read_text() == "hello"


def test_denied_write_does_not_create_file(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    result = run_tool(
        registry, _write_call("a.txt"), approval_fn=lambda request: False, session_id="s"
    )
    assert result.success is False
    assert result.error_type == "ApprovalDenied"
    assert result.approval_decision == "denied"
    assert not (tmp_path / "workspace" / "a.txt").exists()


def test_approval_callback_exception_denies(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)

    def boom(request: ApprovalRequest) -> bool:
        raise RuntimeError("approval backend down")

    result = run_tool(registry, _write_call("a.txt"), approval_fn=boom, session_id="s")
    assert result.success is False
    assert result.approval_decision == "denied"
    assert not (tmp_path / "workspace" / "a.txt").exists()


def test_denied_existing_file_is_unchanged(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    target = tmp_path / "workspace" / "a.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")
    result = run_tool(registry, _write_call("a.txt", "after"), approval_fn=lambda request: False)
    assert result.success is False
    assert target.read_text(encoding="utf-8") == "before"


def test_missing_approval_defaults_to_deny(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    result = run_tool(registry, _write_call("a.txt"), approval_fn=None, session_id="s")
    assert result.success is False
    assert result.approval_decision == "denied"
    assert not (tmp_path / "workspace" / "a.txt").exists()


def test_console_approval_accepts_and_defaults_deny() -> None:
    yes = ConsoleApproval(interactive=True, input_fn=lambda prompt: "y", timeout_seconds=None)
    no = ConsoleApproval(interactive=True, input_fn=lambda prompt: "", timeout_seconds=None)
    non_interactive = ConsoleApproval(interactive=False)
    assert yes(_request()) is True
    assert no(_request()) is False
    assert non_interactive(_request()) is False


def test_console_approval_eof_denies() -> None:
    def eof(prompt: str) -> str:
        raise EOFError

    approval = ConsoleApproval(interactive=True, input_fn=eof, timeout_seconds=None)
    assert approval(_request()) is False


def test_explicit_idempotency_key_is_scoped_by_tool() -> None:
    args = {"idempotency_key": "k1"}
    first = idempotency_key("s", "tool_a", args)
    second = idempotency_key("s", "tool_b", args)
    assert first != second
    assert first == idempotency_key("s", "tool_a", args)


def test_console_approval_timeout_denies() -> None:
    def timeout(prompt: str) -> str:
        raise TimeoutError

    approval = ConsoleApproval(interactive=True, input_fn=timeout)
    assert approval(_request()) is False


def test_single_process_idempotency_deduplicates(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    cache = IdempotencyCache()
    first = run_tool(
        registry,
        _write_call("same.txt", "same"),
        approval_fn=lambda request: True,
        session_id="s",
        cache=cache,
    )
    second = run_tool(
        registry,
        _write_call("same.txt", "same"),
        approval_fn=lambda request: True,
        session_id="s",
        cache=cache,
    )
    assert first.success and second.success
    assert second.deduplicated is True
    assert len((tmp_path / "workspace" / "same.txt").read_text()) == 4


def test_same_path_same_content_is_idempotent_on_disk(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    call = _write_call("same.txt", "same")
    first = run_tool(registry, call, approval_fn=lambda request: True, session_id="s")
    second = run_tool(registry, call, approval_fn=lambda request: True, session_id="s")
    assert first.success and second.success
    assert "未变化" in str(second)


@pytest.mark.parametrize("path", ["../escape.txt", "/tmp/absolute-escape.txt"])
def test_write_rejects_escape_paths(tmp_path: Path, path: str) -> None:
    registry = _write_registry(tmp_path)
    result = run_tool(registry, _write_call(path), approval_fn=lambda request: True, session_id="s")
    assert result.success is False
    assert not (tmp_path.parent / "escape.txt").exists()


def test_write_rejects_symlink_escape(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    result = run_tool(
        registry,
        _write_call("link/escape.txt"),
        approval_fn=lambda request: True,
        session_id="s",
    )
    assert result.success is False
    assert not (outside / "escape.txt").exists()


def test_write_rejects_oversize_content(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    result = run_tool(
        registry,
        _write_call("big.txt", "x" * (64 * 1024 + 1)),
        approval_fn=lambda request: True,
        session_id="s",
    )
    assert result.success is False
    assert not (tmp_path / "workspace" / "big.txt").exists()


def test_agent_tool_event_contains_approval_audit(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    events: list[dict] = []
    llm = _ScriptedLLM(
        [
            json.dumps(
                {
                    "action": "write_workspace_file",
                    "action_input": {"path": "audit.txt", "content": "secret-body"},
                }
            ),
            '{"action": "final_answer", "action_input": "done"}',
        ]
    )
    agent = Agent(
        registry,
        llm_client=llm,
        approval_fn=lambda request: True,
        on_event=events.append,
        session_id="s",
    )
    assert agent.run("write", []) == "done"
    assert (tmp_path / "workspace" / "audit.txt").read_text() == "secret-body"

    tool = next(event for event in events if event["event"] == "tool")
    assert tool["decision"] == "approved"
    assert tool["approval_decision"] == "approved"
    assert tool["reviewer"] == "injected"
    assert tool["idempotency_key"]
    assert tool["approval_timestamp"]
    assert "timestamp" not in tool
    assert "secret-body" not in tool["argument_summary"]


def test_denied_tool_event_contains_audit(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    events: list[dict] = []
    llm = _ScriptedLLM(
        [
            '{"action": "write_workspace_file", "action_input": {"path": "denied.txt", "content": "secret"}}',
            '{"action": "final_answer", "action_input": "done"}',
        ]
    )
    agent = Agent(
        registry,
        llm_client=llm,
        approval_fn=lambda request: False,
        on_event=events.append,
        session_id="s",
    )
    assert agent.run("write", []) == "done"
    assert not (tmp_path / "workspace" / "denied.txt").exists()
    tool = next(event for event in events if event["event"] == "tool")
    assert tool["decision"] == "denied"
    assert tool["error_type"] == "ApprovalDenied"
    assert tool["approval_timestamp"]
    assert "secret" not in tool["argument_summary"]


def test_cli_help_contract_unchanged() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agentkernel", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--db" in proc.stdout
    assert "--mcp-profile" in proc.stdout

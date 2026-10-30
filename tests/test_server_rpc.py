"""MCP server JSON-RPC 与 stdio 循环（补齐 server.py 未覆盖分支）。"""

from __future__ import annotations

import io
import json

import pytest

from agentkernel.mcp.framing import MCPFramingError, frame_message, read_frame
from agentkernel.mcp.server import KnowledgeMCPServer, handle_json_rpc, run_stdio
from agentkernel.rag.ingest import KnowledgeBase


@pytest.fixture()
def server() -> KnowledgeMCPServer:
    kb = KnowledgeBase(persist_dir=None)
    kb.ingest_text("notes.md", "ReAct 是 Reasoning + Acting 的循环，AgentKernel 从零实现。")
    return KnowledgeMCPServer(kb)


def test_initialize_and_tools_list(server: KnowledgeMCPServer) -> None:
    init = handle_json_rpc(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init and init["result"]["protocolVersion"] == "2024-11-05"
    listed = handle_json_rpc(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"knowledge_query", "knowledge_list"}


def test_notification_returns_none(server: KnowledgeMCPServer) -> None:
    assert (
        handle_json_rpc(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )


def test_tools_call_success(server: KnowledgeMCPServer) -> None:
    response = handle_json_rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "knowledge_query", "arguments": {"query": "ReAct", "top_k": 1}},
        },
    )
    assert response and "ReAct" in response["result"]["content"][0]["text"]


def test_tools_call_arguments_must_be_object(server: KnowledgeMCPServer) -> None:
    response = handle_json_rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "x", "arguments": []},
        },
    )
    assert response and response["error"]["code"] == -32602


def test_tools_call_agent_error_maps_to_32602(server: KnowledgeMCPServer) -> None:
    response = handle_json_rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "knowledge_query", "arguments": {"query": "x", "top_k": 0}},
        },
    )
    assert response and response["error"]["code"] == -32602


def test_tools_call_unexpected_error_maps_to_32603(
    server: KnowledgeMCPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(name: str, arguments: dict) -> str:
        raise RuntimeError("db down")

    monkeypatch.setattr(server, "call_tool", boom)
    response = handle_json_rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "knowledge_query", "arguments": {}},
        },
    )
    assert response and response["error"]["code"] == -32603
    assert "内部错误" in response["error"]["message"]


def test_unknown_method(server: KnowledgeMCPServer) -> None:
    response = handle_json_rpc(server, {"jsonrpc": "2.0", "id": 7, "method": "nope"})
    assert response and response["error"]["code"] == -32601


def test_run_stdio_handles_bad_json_and_eof(server: KnowledgeMCPServer) -> None:
    stdin = io.BytesIO(
        frame_message(b'{"jsonrpc":"2.0","id":1,"method":"initialize"}')
        + frame_message(b"{not json}")
        + frame_message(b"\xff\xfe")
    )
    stdout = io.BytesIO()
    with pytest.raises(MCPFramingError):
        run_stdio(server, stdin=stdin, stdout=stdout)

    stdout.seek(0)
    responses = []
    while True:
        try:
            responses.append(json.loads(read_frame(stdout)))
        except Exception:
            break
    assert responses[0]["result"]["serverInfo"]["name"] == "agentkernel-knowledge"
    assert responses[1]["error"]["code"] == -32700
    assert responses[2]["error"]["code"] == -32700

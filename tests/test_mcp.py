"""MCP server / client 测试（进程内适配器 + 自实现 client 的帧协议 + stdio 子进程）。"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from agentkernel.mcp.client import InProcessMCPClient, StdioMCPClient, _frame_message, _read_frame, register_mcp_tools
from agentkernel.mcp.server import KnowledgeMCPServer, handle_json_rpc
from agentkernel.rag.ingest import KnowledgeBase
from agentkernel.tools.registry import Registry
from agentkernel.utils.errors import ToolParamError


def _make_server():
    kb = KnowledgeBase()
    kb.ingest_text("notes.md", "AgentKernel 从零实现 ReAct 主循环，支持工具调用。")
    return KnowledgeMCPServer(kb)


def test_knowledge_query_with_citation():
    server = _make_server()
    out = server.call_tool("knowledge_query", {"query": "什么是 ReAct", "top_k": 1})
    assert "来源：notes.md" in out
    assert "ReAct" in out


def test_knowledge_list():
    server = _make_server()
    out = server.call_tool("knowledge_list", {})
    assert "notes.md" in out


def test_knowledge_query_param_error():
    server = _make_server()
    try:
        server.call_tool("knowledge_query", {})
        raise AssertionError("应当抛参数错误")
    except ToolParamError as e:
        assert "query" in str(e)


def test_register_mcp_tools_into_registry():
    client = InProcessMCPClient(_make_server())
    registry = Registry()
    count = register_mcp_tools(registry, client)
    assert count == 2
    assert "knowledge_query" in registry.names()
    out = registry.run("knowledge_query", {"query": "ReAct 是什么"})
    assert "来源：notes.md" in out


def test_register_mcp_tools_with_prefix():
    client = InProcessMCPClient(_make_server())
    registry = Registry()
    register_mcp_tools(registry, client, prefix="mcp0_")
    assert "mcp0_knowledge_query" in registry.names()
    out = registry.run("mcp0_knowledge_query", {"query": "ReAct 是什么"})
    assert "来源：notes.md" in out


def test_extract_tool_result_structured_content():
    from agentkernel.mcp.client import StdioMCPClient

    text = StdioMCPClient._extract_tool_result(
        "demo", {"structuredContent": {"items": [1, 2]}}
    )
    assert text == '{"items": [1, 2]}'


def test_handle_json_rpc_tools_call_and_errors():
    server = _make_server()
    ok = handle_json_rpc(
        server,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "knowledge_query", "arguments": {"query": "ReAct"}}},
    )
    assert ok is not None and ok.get("result", {}).get("content")[0]["text"]

    not_found = handle_json_rpc(
        server,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}},
    )
    assert not_found is not None and not_found.get("error", {}).get("code") == -32602


def test_frame_roundtrip():
    body = b'{"jsonrpc":"2.0","id":1}'
    stream = io.BytesIO(_frame_message(body))
    assert _read_frame(stream) == body


def test_stdio_client_against_self_hosted_server(tmp_path):
    """自实现 client 通过 stdio 子进程调用自建 MCP server（agent-study Ch10.6）。"""
    doc = tmp_path / "notes.md"
    doc.write_text("AgentKernel 从零实现 ReAct 主循环，支持工具调用。", encoding="utf-8")

    project_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    src_path = str(project_root / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")

    client = StdioMCPClient(
        [
            sys.executable,
            "-m",
            "agentkernel.mcp.server",
            "--kb-db",
            str(tmp_path / "kb"),
            str(doc),
        ]
    )
    try:
        tools = client.list_tools()
        names = {t["name"] for t in tools}
        assert "knowledge_query" in names
        assert "knowledge_list" in names
        assert client.negotiated
        assert client.protocol_version
        assert client.server_info.get("name") == "agentkernel-knowledge"

        out = client.call_tool("knowledge_query", {"query": "ReAct 是什么"})
        assert "来源：notes.md" in out
    finally:
        client.close()

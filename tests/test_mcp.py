"""MCP server / client 测试（进程内适配器 + 自实现 client 的帧协议）。"""
from __future__ import annotations

from agentkernel.mcp.client import InProcessMCPClient, StdioMCPClient, _frame_message, _read_frame, register_mcp_tools
from agentkernel.mcp.server import KnowledgeMCPServer
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


def test_frame_roundtrip():
    import io

    body = b'{"jsonrpc":"2.0","id":1}'
    stream = io.BytesIO(_frame_message(body))
    assert _read_frame(stream) == body

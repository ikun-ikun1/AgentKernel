"""自实现 MCP client：initialize → tools/list → tools/call，注册进内核。

个人项目特点：client 端不调官方 SDK，手写 MCP stdio 传输（Content-Length 帧 + JSON-RPC 2.0），
证明懂协议底层；同时提供 InProcessMCPClient 作为无 SDK 环境下的演示/测试适配器。
"""
from __future__ import annotations
import json
import subprocess
from typing import Any

from agentkernel.mcp.framing import frame_message, read_frame
from agentkernel.tools.registry import Registry, Tool
from agentkernel.utils.errors import AgentKernelError


class MCPClientError(AgentKernelError):
    """MCP client 协议/调用错误。"""


class MCPClient:
    """MCP client 协议接口：列出工具 + 调用工具。"""

    def list_tools(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


# 向后兼容：测试/教学代码可继续从 client 导入帧工具
_frame_message = frame_message
_read_frame = read_frame


class StdioMCPClient(MCPClient):
    """手写 MCP stdio 传输 + JSON-RPC 2.0。"""

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self._proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1

    def start(self) -> "StdioMCPClient":
        if self._proc is not None:
            return self
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return self

    def _send(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        self._proc.stdin.write(_frame_message(data))
        self._proc.stdin.flush()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.start()
        assert self._proc is not None and self._proc.stdout is not None
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        while True:
            body = _read_frame(self._proc.stdout)
            try:
                message = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise MCPClientError(f"MCP server 返回非法 JSON：{e}") from e
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPClientError(f"MCP 错误：{message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise MCPClientError("MCP 响应缺少 result")
            return result

    def initialize(self) -> dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agentkernel-mcp-client", "version": "0.1.0"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self._request("tools/list")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise MCPClientError("tools/list 返回格式错误")
        return [t for t in tools if isinstance(t, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        content = result.get("content")
        if not isinstance(content, list):
            raise MCPClientError("tools/call 返回格式错误")
        text_parts = [
            str(item["text"])
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item
        ]
        if result.get("isError"):
            raise MCPClientError("；".join(text_parts) or f"工具 {name} 调用失败")
        return "\n".join(text_parts)

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


class InProcessMCPClient(MCPClient):
    """进程内 MCP 适配器：直接包装 KnowledgeMCPServer，测试/无 SDK 演示用。"""

    def __init__(self, server: Any) -> None:
        self.server = server

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self.server.tool_definitions())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return self.server.call_tool(name, arguments)


def register_mcp_tools(registry: Registry, client: MCPClient) -> int:
    """把 MCP client 暴露的工具注册进内核 registry，返回注册数量。

    注册后内核把 MCP 工具当普通工具调用，对模型无感知（架构上的关键点）。
    """
    count = 0
    for tool_def in client.list_tools():
        name = tool_def.get("name")
        description = tool_def.get("description", "")
        schema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}
        if not isinstance(name, str) or not name:
            continue

        def make_fn(tool_name: str):
            def fn(args: dict[str, Any]) -> str:
                return client.call_tool(tool_name, args)

            return fn

        registry.register(
            Tool(name=name, description=description, parameters=schema, fn=make_fn(name))
        )
        count += 1
    return count

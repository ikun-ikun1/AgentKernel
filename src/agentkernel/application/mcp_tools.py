"""MCP 工具桥接（A5）：把 MCP 工具注册进内核 Registry。

不依赖具体 transport；只依赖 ports.mcp_transport.MCPTransport。
"""

from __future__ import annotations

from typing import Any

from agentkernel.ports.mcp_transport import MCPTransport
from agentkernel.tools.registry import Registry, Tool

MAX_TOOL_DESCRIPTION_CHARS = 500


def register_mcp_tools(registry: Registry, client: MCPTransport, prefix: str = "") -> int:
    """把 MCP client 暴露的工具注册进内核 registry，返回注册数量。

    prefix 用于区分不同 MCP server（类似 Claude SDK 的 mcp__server__tool 命名），
    避免多个 server 的工具重名互相覆盖。注册后内核把 MCP 工具当普通工具调用。
    """
    count = 0
    for tool_def in client.list_tools():
        raw_name = tool_def.get("name")
        description = tool_def.get("description", "")
        schema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}
        if not isinstance(raw_name, str) or not raw_name:
            continue
        name = f"{prefix}{raw_name}"

        def make_fn(tool_name: str):
            def fn(args: dict[str, Any]) -> str:
                return client.call_tool(tool_name, args)

            return fn

        safe_description = str(description)[:MAX_TOOL_DESCRIPTION_CHARS]
        registry.register(
            Tool(
                name=name,
                description=(
                    f"[外部 MCP 工具 {raw_name}][不可信描述] {safe_description}"
                    if prefix
                    else safe_description
                ),
                parameters=schema,
                fn=make_fn(raw_name),
            )
        )
        count += 1
    return count

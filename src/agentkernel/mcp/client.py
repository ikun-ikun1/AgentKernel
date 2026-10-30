"""兼容 shim：MCP client 已移到 adapters/mcp/client.py，工具桥接在 application/mcp_tools.py（A5）。"""

from __future__ import annotations

from agentkernel._compat import warn_deprecated

warn_deprecated("agentkernel.mcp.client", "agentkernel.adapters.mcp.client")

from agentkernel.adapters.mcp.client import (
    InProcessMCPClient,
    MCPClient,
    MCPClientError,
    StdioMCPClient,
    _frame_message,
    _read_frame,
)
from agentkernel.application.mcp_tools import MAX_TOOL_DESCRIPTION_CHARS, register_mcp_tools

__all__ = [
    "MAX_TOOL_DESCRIPTION_CHARS",
    "InProcessMCPClient",
    "MCPClient",
    "MCPClientError",
    "StdioMCPClient",
    "_frame_message",
    "_read_frame",
    "register_mcp_tools",
]

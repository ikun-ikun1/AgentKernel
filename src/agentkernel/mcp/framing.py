"""兼容 shim：MCP 帧协议已移到 protocol/mcp_framing.py（A5）。"""

from __future__ import annotations

from agentkernel._compat import warn_deprecated

warn_deprecated("agentkernel.mcp.framing", "agentkernel.protocol.mcp_framing")

from agentkernel.protocol.mcp_framing import (
    DEFAULT_MAX_FRAME_BYTES,
    MAX_HEADER_BYTES,
    MCPFramingError,
    frame_message,
    read_frame,
    write_message,
)

__all__ = [
    "DEFAULT_MAX_FRAME_BYTES",
    "MAX_HEADER_BYTES",
    "MCPFramingError",
    "frame_message",
    "read_frame",
    "write_message",
]

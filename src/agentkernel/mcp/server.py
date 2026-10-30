"""兼容 shim：知识库 MCP server 已移到 adapters/mcp/knowledge_server.py（A5）。"""

from __future__ import annotations

from agentkernel.adapters.mcp.knowledge_server import (
    TOOL_DEFINITIONS,
    KnowledgeMCPServer,
    MCPToolError,
    format_results,
    handle_json_rpc,
    main,
    run_stdio,
)

__all__ = [
    "TOOL_DEFINITIONS",
    "KnowledgeMCPServer",
    "MCPToolError",
    "format_results",
    "handle_json_rpc",
    "main",
    "run_stdio",
]

if __name__ == "__main__":
    main()

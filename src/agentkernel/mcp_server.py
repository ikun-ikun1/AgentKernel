"""Canonical MCP server entrypoint（v0.3.1）。

用法：python -m agentkernel.mcp_server
旧入口 python -m agentkernel.mcp.server 仍可用但会发 DeprecationWarning，v0.4.0 删除。
"""

from __future__ import annotations

from agentkernel.adapters.mcp.knowledge_server import main

__all__ = ["main"]

if __name__ == "__main__":
    main()

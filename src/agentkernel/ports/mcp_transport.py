"""MCP 传输端口（A5）：client 只需暴露工具发现/调用/关闭。"""

from __future__ import annotations

from typing import Any, Protocol


class MCPTransport(Protocol):
    def list_tools(self) -> list[dict[str, Any]]:
        """返回 MCP server 的工具定义。"""
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """调用一个 MCP 工具并返回文本结果。"""
        ...

    def close(self) -> None:
        """关闭传输。"""
        ...

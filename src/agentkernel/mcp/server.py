"""知识库 MCP server：knowledge_query(query, top_k) + knowledge_list()。

- 优先用官方 `mcp` SDK（FastMCP）暴露工具；SDK 未安装时退化为进程内可调用的
  `KnowledgeMCPServer`，保证 client 端和测试在无重依赖环境下也能跑通。
- server 只暴露「查询 + 列出」两个只读工具，不提供写/删能力（安全边界）。
"""
from __future__ import annotations
from typing import Any

from agentkernel.rag.ingest import KnowledgeBase, SearchResult
from agentkernel.tools.registry import validate_parameters
from agentkernel.utils.errors import AgentKernelError


class MCPToolError(AgentKernelError):
    """MCP 工具调用错误。"""


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "knowledge_query",
        "description": "检索知识库，返回带来源的文档片段。参数 query 是查询问题，top_k 控制返回条数",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询问题"},
                "top_k": {"type": "integer", "description": "返回条数，默认 3"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "knowledge_list",
        "description": "列出知识库中已入库的文档名",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def format_results(results: list[SearchResult]) -> str:
    """把检索结果格式化为带来源引用的文本。"""
    if not results:
        return "（知识库中未找到相关内容）"
    lines = [f"{i}. {r.to_citation()}" for i, r in enumerate(results, 1)]
    return "\n".join(lines)


class KnowledgeMCPServer:
    """知识库 MCP 工具的纯 Python 实现（进程内可调、可测试）。"""

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def tool_definitions(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        definition = next((t for t in TOOL_DEFINITIONS if t["name"] == name), None)
        if definition is None:
            raise MCPToolError(f"未知 MCP 工具：{name}")
        validate_parameters(definition["inputSchema"], arguments, f"工具 {name} 参数")
        if name == "knowledge_query":
            return self.knowledge_query(str(arguments["query"]), int(arguments.get("top_k", 3)))
        if name == "knowledge_list":
            return self.knowledge_list()
        raise MCPToolError(f"工具 {name} 未实现")

    def knowledge_query(self, query: str, top_k: int = 3) -> str:
        query = query.strip()
        if not query:
            raise MCPToolError("query 不能为空")
        if top_k < 1:
            raise MCPToolError("top_k 必须 >= 1")
        return format_results(self.kb.query(query, top_k=top_k))

    def knowledge_list(self) -> str:
        docs = self.kb.list_documents()
        if not docs:
            return "（知识库为空）"
        return "\n".join(f"- {doc}" for doc in docs)

    def create_fastmcp(self) -> Any:
        """尝试用官方 mcp SDK 注册工具；未安装则抛 MCPToolError。"""
        try:
            from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
        except ImportError as e:
            raise MCPToolError(
                "官方 mcp SDK 未安装：pip install mcp"
            ) from e

        server = FastMCP("agentkernel-knowledge")
        server.tool(name="knowledge_query", description=TOOL_DEFINITIONS[0]["description"])(
            self.knowledge_query
        )
        server.tool(name="knowledge_list", description=TOOL_DEFINITIONS[1]["description"])(
            self.knowledge_list
        )
        return server

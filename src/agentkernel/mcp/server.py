"""知识库 MCP server：knowledge_query(query, top_k) + knowledge_list()。

- 优先用官方 `mcp` SDK（FastMCP）暴露工具；SDK 未安装时退化为进程内可调用的
  `KnowledgeMCPServer`，保证 client 端和测试在无重依赖环境下也能跑通。
- server 只暴露「查询 + 列出」两个只读工具，不提供写/删能力（安全边界）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
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


# ---------------------------------------------------------------------------
# 纯 Python stdio JSON-RPC 入口（教学点：agent-study Ch10.6 stdio 传输）
# 无 mcp SDK 时也能启动一个标准 MCP stdio server，供自实现 client 子进程调用。
# 协议消息走 stdout；日志/错误走 stderr。
# ---------------------------------------------------------------------------

def handle_json_rpc(server: KnowledgeMCPServer, request: dict[str, Any]) -> dict[str, Any] | None:
    """处理一个 JSON-RPC 请求；通知（无 id）返回 None。"""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agentkernel-knowledge", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": server.tool_definitions()},
        }
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "arguments 必须是对象"},
            }
        try:
            text = server.call_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text}], "isError": False},
            }
        except AgentKernelError as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": str(e)},
            }
        except Exception as e:  # 兜底：server 内部意外异常也要转成 JSON-RPC 错误
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"内部错误: {type(e).__name__}: {e}"},
            }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"未知方法: {method}"},
    }


def run_stdio(server: KnowledgeMCPServer, stdin: Any = None, stdout: Any = None) -> None:
    """标准 MCP stdio 服务循环：Content-Length 帧 + JSON-RPC 2.0。"""
    from agentkernel.mcp.framing import read_frame, write_message

    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer

    while True:
        body = read_frame(stdin)
        try:
            request = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            write_message(
                stdout,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                },
            )
            continue
        response = handle_json_rpc(server, request)
        if response is not None:
            write_message(stdout, response)


def main(argv: list[str] | None = None) -> None:
    """Start the stdio server and incrementally ingest supplied documents."""
    parser = argparse.ArgumentParser(description="AgentKernel knowledge MCP server")
    parser.add_argument("paths", nargs="*", metavar="PATH", help="PDF/MD/TXT file or directory")
    parser.add_argument(
        "--kb-db",
        default=os.environ.get("AGENTKERNEL_KB_DSN") or "~/.agentkernel/knowledge",
        help="knowledge store: mysql+pymysql://... DSN or local path (SQLite adapter)",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "lexical", "hybrid", "semantic"),
        default="lexical",
        help="retrieval backend; hybrid/semantic explicitly enable vector models",
    )
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    kb_dsn = (
        parsed.kb_db
        if parsed.kb_db.startswith("mysql://") or parsed.kb_db.startswith("mysql+pymysql://")
        else None
    )
    kb = KnowledgeBase(
        persist_dir=None if kb_dsn else parsed.kb_db,
        backend=parsed.backend,
        dsn=kb_dsn,
    )
    for path in parsed.paths:
        path_obj = Path(path).expanduser()
        if path_obj.is_dir():
            files = sorted(
                f for f in path_obj.rglob("*")
                if f.is_file() and f.suffix.lower() in {".pdf", ".md", ".markdown", ".txt"}
            )
        elif path_obj.is_file():
            files = [path_obj]
        else:
            print(f"跳过不存在的路径：{path_obj}", file=sys.stderr)
            continue
        for file in files:
            try:
                chunks = kb.ingest_file(file)
                if chunks:
                    print(f"已入库 {file.name}（{chunks} 块）", file=sys.stderr)
                else:
                    print(f"已跳过（内容未变化）：{file.name}", file=sys.stderr)
            except Exception as e:
                print(f"入库失败 {file.name}：{e}", file=sys.stderr)

    run_stdio(KnowledgeMCPServer(kb))


if __name__ == "__main__":
    main()

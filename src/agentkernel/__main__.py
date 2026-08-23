"""CLI 入口：`python -m agentkernel` 启动交互式对话。

内置命令（以 `/` 开头）：
- /new [标题]   新建会话并切换过去
- /sessions     列出最近会话
- /history      查看当前会话历史
- /ingest <路径> 入库文档（PDF/MD/TXT），之后可问知识库问题
- /docs         列出已入库文档
- /logs         查看当前会话的工具调用审计
- /help         查看帮助
- /quit         退出（同 quit / exit / q）

知识库工具（knowledge_query / knowledge_list）默认注册；用 `--docs` 启动时直接入库。
用 `--mcp` 可接入任意外部 stdio MCP server（类似 Claude Agent SDK 的 mcp_servers 配置）。
"""
from __future__ import annotations

import argparse
import shlex
import sys
import uuid
from pathlib import Path

from agentkernel.mcp.client import InProcessMCPClient, MCPClient, StdioMCPClient, register_mcp_tools
from agentkernel.mcp.server import KnowledgeMCPServer
from agentkernel.memory.sqlite_store import SQLiteStore, default_store
from agentkernel.rag.ingest import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry

_SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}


def _print_help() -> None:
    print(
        "内置命令：/new [标题] | /sessions | /history | /ingest <路径> | /docs | /logs | /help | /quit\n"
        "其他输入都会交给 Agent 处理。"
    )


def _load_history(store: SQLiteStore, session_id: str) -> list[dict[str, str]]:
    return store.get_messages(session_id)


def _ingest_path(kb: KnowledgeBase, path: str) -> int:
    """入库一个文件或目录，返回入库文档数。"""
    p = Path(path).expanduser()
    if not p.exists():
        print(f"路径不存在：{p}")
        return 0
    files = [p] if p.is_file() else sorted(
        f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in _SUPPORTED_SUFFIXES
    )
    total = 0
    for file in files:
        try:
            chunks = kb.ingest_file(file)
            print(f"已入库 {file.name}（{chunks} 块）")
            total += 1
        except Exception as e:
            print(f"入库失败 {file.name}：{type(e).__name__}: {e}")
    return total


def _build_agent(
    docs: list[str] | None = None,
    kb_db: str | None = None,
    mcp_commands: list[str] | None = None,
) -> tuple[Agent, Registry, KnowledgeBase, list[MCPClient]]:
    registry = Registry()
    builtin.register_builtin(registry)

    # kb_db 为空时使用纯 Python 降级索引；给路径时优先 ChromaDB（未装则自动降级）
    kb = KnowledgeBase(persist_dir=kb_db)
    if docs:
        for path in docs:
            _ingest_path(kb, path)
    server = KnowledgeMCPServer(kb)
    register_mcp_tools(registry, InProcessMCPClient(server))

    # 外部 stdio MCP server（类似 Claude SDK 的 mcp_servers 配置）
    external_clients: list[MCPClient] = []
    for idx, cmd in enumerate(mcp_commands or []):
        try:
            argv = shlex.split(cmd)
            if not argv:
                continue
            # 用户习惯写 `python -m ...` 时，用当前解释器（.venv）保证子进程环境一致
            if argv[0] in ("python", "python3"):
                argv[0] = sys.executable
            client = StdioMCPClient(argv)
            prefix = f"mcp{idx}_"
            n = register_mcp_tools(registry, client, prefix=prefix)
            external_clients.append(client)
            print(f"已接入外部 MCP server（{n} 个工具，前缀 {prefix}）：{cmd}")
        except Exception as e:
            print(f"接入外部 MCP server 失败（{cmd}）：{type(e).__name__}: {e}")

    return Agent(registry), registry, kb, external_clients


def _repl(store: SQLiteStore, kb: KnowledgeBase, agent: Agent) -> None:
    session_id = "default"
    store.create_session(session_id)

    def _log_tool_call(tool_name: str, action_input: dict[str, object], result: str) -> None:
        ok = not result.startswith("[工具")
        store.log_tool_call(session_id, tool_name, action_input, result, ok)

    agent.on_tool_call = _log_tool_call

    print("AgentKernel 已启动（/help 查看内置命令，Ctrl+C 中断）")
    history: list[dict[str, str]] = _load_history(store, session_id)

    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd, _, arg = user_input[1:].partition(" ")
            cmd = cmd.lower()
            if cmd in ("quit", "q", "exit"):
                print("再见")
                break
            if cmd == "help":
                _print_help()
                continue
            if cmd == "new":
                session_id = uuid.uuid4().hex[:8]
                store.create_session(session_id, arg.strip() or session_id)
                history = _load_history(store, session_id)
                print(f"已新建会话 {session_id}（历史已清空）")
                continue
            if cmd == "sessions":
                sessions = store.list_sessions()
                if not sessions:
                    print("（暂无会话）")
                for s in sessions:
                    mark = "← 当前" if s["id"] == session_id else ""
                    print(f"- {s['id']}  {s['title']}  （更新于 {s['updated_at'][:19]}）{mark}")
                continue
            if cmd == "history":
                msgs = store.get_messages(session_id)
                if not msgs:
                    print("（当前会话暂无历史）")
                for m in msgs:
                    who = "你" if m["role"] == "user" else "Agent"
                    print(f"{who} > {m['content']}")
                continue
            if cmd in ("ingest", "kb"):
                if not arg.strip():
                    print("用法：/ingest <文件或目录路径>")
                    continue
                _ingest_path(kb, arg.strip())
                continue
            if cmd == "docs":
                docs = kb.list_documents()
                if not docs:
                    print("（知识库为空，用 /ingest <路径> 入库文档）")
                for doc in docs:
                    print(f"- {doc}")
                continue
            if cmd == "logs":
                logs = store.list_tool_logs(session_id)
                if not logs:
                    print("（当前会话暂无工具调用记录）")
                for log in logs:
                    status = "成功" if log["success"] else "失败"
                    print(
                        f"- {log['created_at'][:19]} {log['tool_name']} {status}\n"
                        f"  入参：{log['input_json']}\n  结果：{str(log['output_json'])[:120]}"
                    )
                continue
            print(f"未知命令 /{cmd}，输入 /help 查看帮助")
            continue

        # 普通输入：先持久化用户消息，再跑 Agent，最后持久化最终回答。
        store.append_message(session_id, "user", user_input)
        print("Agent > ", end="", flush=True)
        try:
            reply = agent.run(user_input, history)
        except Exception as e:  # 模型失败等不应打断 CLI
            reply = f"[AgentKernel 错误] {type(e).__name__}: {e}"
        print(reply)
        store.append_message(session_id, "assistant", reply)
        # 以 DB 的干净历史为准：内部 ReAct 观察信息不落库，避免污染后续上下文。
        history = _load_history(store, session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentKernel CLI")
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite 库文件路径（默认 ~/.agentkernel/agentkernel.db，可用 :memory:）",
    )
    parser.add_argument(
        "--docs",
        nargs="+",
        default=None,
        metavar="PATH",
        help="启动时入库的文档（文件或目录，支持 PDF/MD/TXT）",
    )
    parser.add_argument(
        "--kb-db",
        default=None,
        metavar="PATH",
        help="知识库持久化目录（启用 ChromaDB 后端；缺依赖时自动降级纯 Python 索引）",
    )
    parser.add_argument(
        "--mcp",
        action="append",
        default=None,
        metavar="CMD",
        help="接入外部 stdio MCP server（可多次使用），如 --mcp \"python -m agentkernel.mcp.server /tmp/docs\"",
    )
    args = parser.parse_args()

    store = default_store() if args.db is None else SQLiteStore(args.db)
    agent, _, kb, clients = _build_agent(args.docs, args.kb_db, args.mcp)
    print(f"知识库后端：{kb.backend_name}")
    try:
        _repl(store, kb, agent)
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        store.close()


if __name__ == "__main__":
    main()

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
外部 MCP server 用 `--mcp-profile <name>` 接入（命令/参数/环境来自 profile 文件，不接受任意命令字符串）。
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
import uuid
from pathlib import Path

from agentkernel.mcp.client import InProcessMCPClient, MCPClient, StdioMCPClient, register_mcp_tools
from agentkernel.mcp.profiles import (
    McpProfileError,
    build_child_env,
    load_profiles,
    select_profile,
)
from agentkernel.mcp.server import KnowledgeMCPServer
from agentkernel.memory.base import RuntimeStore
from agentkernel.memory.factory import create_runtime_store
from agentkernel.rag.ingest import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry
from agentkernel.utils import env as env_utils
from agentkernel.utils import observability
from agentkernel.utils import paths as path_utils

_SUPPORTED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}


def _redact_dsn(dsn: str) -> str:
    """隐藏 DSN 中的密码，避免启动日志泄露凭据。"""
    return re.sub(r"(://[^:/?#]+:)[^@/?#]+(@)", r"\1***\2", dsn)


def _print_help() -> None:
    print(
        "内置命令：/new [标题] | /sessions | /history | /ingest <路径> | /docs | /logs | /help | /quit\n"
        "其他输入都会交给 Agent 处理。"
    )


def _load_history(store: RuntimeStore, session_id: str) -> list[dict[str, str]]:
    return store.get_messages(session_id)


def _ingest_path(kb: KnowledgeBase, path: str) -> int:
    """入库一个文件或目录，返回入库文档数；路径越界/超限直接拒绝（P0-5）。"""
    try:
        files = path_utils.collect_documents(path)
    except path_utils.PathBoundaryError as exc:
        print(f"拒绝入库：{exc}")
        return 0
    total = 0
    for file in files:
        try:
            chunks = kb.ingest_file(file)
            if chunks:
                print(f"已入库 {file.name}（{chunks} 块）")
                total += 1
            else:
                print(f"已跳过（内容未变化）：{file.name}")
        except Exception as e:
            print(f"入库失败 {file.name}：{type(e).__name__}: {e}")
    return total


def _build_agent(
    docs: list[str] | None = None,
    kb_db: str | None = None,
    mcp_profiles: list[str] | None = None,
    kb_backend: str = "lexical",
    profiles_file: str | None = None,
    raw_mcp_commands: list[str] | None = None,
) -> tuple[Agent, Registry, KnowledgeBase, list[MCPClient]]:
    registry = Registry()
    builtin.register_builtin(registry)

    # kb_db 支持 MySQL DSN 或本地路径（SQLite 测试适配器）。
    kb_dsn = (
        kb_db
        if kb_db and (kb_db.startswith("mysql://") or kb_db.startswith("mysql+pymysql://"))
        else None
    )
    kb_persist_dir = None if kb_dsn else kb_db
    kb = KnowledgeBase(persist_dir=kb_persist_dir, backend=kb_backend, dsn=kb_dsn)
    if docs:
        for path in docs:
            _ingest_path(kb, path)
    server = KnowledgeMCPServer(kb)
    register_mcp_tools(registry, InProcessMCPClient(server))

    # 外部 stdio MCP server：只接受 profile 声明的命令（P0-5）
    external_clients: list[MCPClient] = []
    profiles = load_profiles(Path(profiles_file) if profiles_file else None)
    for idx, name in enumerate(mcp_profiles or []):
        try:
            profile = select_profile(name, profiles)
            client = StdioMCPClient([profile.command, *profile.args], env=build_child_env(profile))
            prefix = f"mcp{idx}_"
            n = register_mcp_tools(registry, client, prefix=prefix)
            external_clients.append(client)
            print(f"已接入 MCP profile {name}（{n} 个工具，前缀 {prefix}）")
        except (McpProfileError, OSError, ValueError) as e:
            print(
                f"接入 MCP profile 失败（{name}）："
                f"{type(e).__name__}: {observability.redact(str(e))}"
            )

    # 开发逃生口：任意命令必须显式开启，且跳过 argv profile 校验
    for idx, cmd in enumerate(raw_mcp_commands or []):
        if os.environ.get("AGENTKERNEL_ALLOW_RAW_MCP") != "1":
            print("拒绝 --mcp：未启用 AGENTKERNEL_ALLOW_RAW_MCP=1（请改用 --mcp-profile）")
            break
        print("警告：--mcp 是开发逃生口，未经过 profile 校验")
        try:
            argv = shlex.split(cmd)
            if not argv:
                continue
            if argv[0] in ("python", "python3"):
                argv[0] = sys.executable
            client = StdioMCPClient(argv)
            prefix = f"raw{idx}_"
            n = register_mcp_tools(registry, client, prefix=prefix)
            external_clients.append(client)
            print(f"已接入外部 MCP server（{n} 个工具，前缀 {prefix}）")
        except Exception as e:  # 接入失败不阻塞启动
            print(f"接入外部 MCP server 失败：{type(e).__name__}: {observability.redact(str(e))}")

    return Agent(registry), registry, kb, external_clients


def _repl(store: RuntimeStore, kb: KnowledgeBase, agent: Agent) -> None:
    session_id = "default"
    store.create_session(session_id)

    def _log_tool_call(tool_name: str, action_input: dict[str, object], result: str) -> None:
        # Registry returns a str-compatible result carrying explicit status.
        ok = getattr(result, "success", not result.startswith("[工具"))
        store.log_tool_call(
            session_id,
            tool_name,
            action_input,
            result,
            ok,
            duration_ms=getattr(result, "duration_ms", None),
        )

    agent.on_tool_call = _log_tool_call
    agent.session_id = session_id
    agent.on_event = lambda event: observability.emit(
        event["event"], **{k: v for k, v in event.items() if k != "event"}
    )

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
                agent.session_id = session_id
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
                    created = str(log.get("created_at", ""))[:19]
                    tool_name = str(log.get("tool_name", ""))
                    duration = log.get("duration_ms")
                    duration_text = (
                        f" {duration:.1f}ms" if isinstance(duration, (int, float)) else ""
                    )
                    print(
                        f"- {created} {tool_name} {status}{duration_text}\n"
                        f"  入参：{log.get('input_json', '')}\n"
                        f"  结果：{str(log.get('output_json', ''))[:120]}"
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
        help="Runtime 存储 DSN：mysql+pymysql://user:pass@host/db 或 sqlite:///:memory: / 本地路径",
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
        metavar="DSN_OR_PATH",
        help="知识库存储：mysql+pymysql://... 或本地路径/目录；默认读取 AGENTKERNEL_KB_DSN，否则 ~/.agentkernel/knowledge",
    )
    parser.add_argument(
        "--kb-backend",
        choices=("auto", "lexical", "hybrid", "semantic"),
        default="lexical",
        help="知识库后端：lexical 默认稳定；hybrid/semantic 显式启用向量模型",
    )
    parser.add_argument(
        "--mcp-profile",
        action="append",
        default=None,
        metavar="NAME",
        help="接入 profile 文件中声明的 MCP server（可多次）；不接受任意命令字符串",
    )
    parser.add_argument(
        "--mcp-profiles-file",
        default=None,
        metavar="PATH",
        help="profile 文件路径（默认 AGENTKERNEL_MCP_PROFILES 或 ~/.agentkernel/mcp_profiles.toml）",
    )
    parser.add_argument(
        "--mcp",
        action="append",
        default=None,
        metavar="CMD",
        help="（开发逃生口）任意命令，需 AGENTKERNEL_ALLOW_RAW_MCP=1；生产请用 --mcp-profile",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="启动前对 MySQL 主存储执行 Alembic 迁移（upgrade head）",
    )
    args = parser.parse_args()

    import os

    env_utils.load_env()
    observability.configure()
    try:
        env_utils.validate_base_url()
    except env_utils.LLMConfigError as exc:
        parser.exit(2, f"配置错误：{exc}\n")

    if args.migrate:
        dsn = args.db or os.environ.get("AGENTKERNEL_DB_URL")
        if not dsn:
            parser.exit(
                2,
                "--migrate 需要 DSN：传 --db mysql+pymysql://... 或设置 AGENTKERNEL_DB_URL\n",
            )
        if not (dsn.startswith("mysql://") or dsn.startswith("mysql+pymysql://")):
            parser.exit(2, "--migrate 需要 MySQL DSN（--db mysql+pymysql://...）\n")
        try:
            from alembic import command
            from alembic.config import Config
        except ImportError:
            parser.exit(2, "Alembic 未安装：pip install -e '.[mysql]'\n")
        os.environ["AGENTKERNEL_DB_URL"] = dsn
        command.upgrade(Config("alembic.ini"), "head")
        print(f"MySQL 迁移完成：{_redact_dsn(dsn)}")

    try:
        store = create_runtime_store(args.db)
    except Exception as e:
        parser.exit(
            2,
            f"Runtime 存储初始化失败：{type(e).__name__}: "
            f"{observability.redact(str(e))}\n"
            "提示：安装 MySQL 依赖并启动 docker compose，首次使用先执行 --migrate；"
            "或使用 --db sqlite:///:memory:\n",
        )

    kb_dsn_or_path = (
        args.kb_db or os.environ.get("AGENTKERNEL_KB_DSN") or "~/.agentkernel/knowledge"
    )
    try:
        agent, _, kb, clients = _build_agent(
            docs=args.docs,
            kb_db=kb_dsn_or_path,
            mcp_profiles=args.mcp_profile,
            kb_backend=args.kb_backend,
            profiles_file=args.mcp_profiles_file,
            raw_mcp_commands=args.mcp,
        )
    except Exception as e:
        store.close()
        parser.exit(2, f"初始化失败：{type(e).__name__}: {observability.redact(str(e))}\n")
    if kb.dsn:
        print(f"知识库：{kb.backend_name}（MySQL：{_redact_dsn(kb.dsn)}）")
    else:
        print(f"知识库：{kb.backend_name}（持久化目录：{kb.persist_dir or '内存'}）")
    if kb.backend_warning:
        print(f"知识库提示：{kb.backend_warning}")
    try:
        _repl(store, kb, agent)
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        try:
            kb.close()
        except Exception:
            pass
        store.close()


if __name__ == "__main__":
    main()

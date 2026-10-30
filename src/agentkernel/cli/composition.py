"""组合根：注册工具、构建知识库、接入 MCP（A1）。

只负责装配，不含 REPL / argparse；行为与拆分前完全一致：
- 内置工具 + 进程内 knowledge MCP；
- --docs 启动入库；
- 外部 MCP 只走命名 profile（精确 argv + env 白名单）；
- --mcp 逃生口仍需 AGENTKERNEL_ALLOW_RAW_MCP=1。
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from agentkernel.adapters.llm.openai_compatible import OpenAICompatibleClient
from agentkernel.mcp.client import InProcessMCPClient, MCPClient, StdioMCPClient, register_mcp_tools
from agentkernel.mcp.profiles import (
    McpProfileError,
    build_child_env,
    load_profiles,
    select_profile,
)
from agentkernel.mcp.server import KnowledgeMCPServer
from agentkernel.rag.ingest import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry
from agentkernel.utils import observability
from agentkernel.utils import paths as path_utils


def ingest_path(kb: KnowledgeBase, path: str) -> int:
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


def build_agent(
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
            ingest_path(kb, path)
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

    return Agent(registry, llm_client=OpenAICompatibleClient()), registry, kb, external_clients

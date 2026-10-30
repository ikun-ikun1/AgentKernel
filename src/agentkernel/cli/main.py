"""CLI 入口与启动流程（A1）：argparse、退出码、配置校验、清理。

REPL 在 cli/repl.py，装配在 cli/composition.py；这里只负责启动顺序与错误呈现。
行为契约：参数、帮助文案、退出码、输出顺序与拆分前一致。
"""

from __future__ import annotations

import argparse
import os
import re

from agentkernel.cli.composition import build_agent
from agentkernel.cli.repl import run_repl
from agentkernel.config.settings import Settings
from agentkernel.memory.factory import create_runtime_store
from agentkernel.utils import env as env_utils
from agentkernel.utils import observability


def _redact_dsn(dsn: str) -> str:
    """隐藏 DSN 中的密码，避免启动日志泄露凭据。"""
    return re.sub(r"(://[^:/?#]+:)[^@/?#]+(@)", r"\1***\2", dsn)


def _build_parser() -> argparse.ArgumentParser:
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
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    settings = Settings.from_args(args)

    observability.configure()
    try:
        env_utils.validate_base_url()
    except env_utils.LLMConfigError as exc:
        parser.exit(2, f"配置错误：{exc}\n")

    if settings.migrate:
        dsn = settings.db_dsn or os.environ.get("AGENTKERNEL_DB_URL")
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
        store = create_runtime_store(settings.db_dsn)
    except Exception as e:
        parser.exit(
            2,
            f"Runtime 存储初始化失败：{type(e).__name__}: "
            f"{observability.redact(str(e))}\n"
            "提示：安装 MySQL 依赖并启动 docker compose，首次使用先执行 --migrate；"
            "或使用 --db sqlite:///:memory:\n",
        )

    try:
        agent, _, kb, clients = build_agent(
            docs=list(settings.docs),
            kb_db=settings.kb_db,
            mcp_profiles=list(settings.mcp_profiles),
            kb_backend=settings.kb_backend,
            profiles_file=settings.mcp_profiles_file,
            raw_mcp_commands=list(settings.raw_mcp_commands),
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
        run_repl(store, kb, agent)
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

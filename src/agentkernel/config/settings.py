"""集中配置：把 env 读取从 CLI/组合根收口到这里（A1）。

行为约定：只做「读取 + 默认值」，不创建连接、不打印、不抛配置错误；
DSN/allowlist 的校验仍由 main 的启动流程负责，保持退出码与错误文案不变。
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from agentkernel.utils import env


@dataclass(frozen=True)
class Settings:
    db_dsn: str | None
    docs: tuple[str, ...]
    kb_db: str
    kb_backend: str
    mcp_profiles: tuple[str, ...]
    mcp_profiles_file: str | None
    raw_mcp_commands: tuple[str, ...]
    migrate: bool

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Settings:
        """加载 .env 并把 argparse 结果规整为不可变配置。"""
        env.load_env()
        return cls(
            db_dsn=args.db,
            docs=tuple(args.docs or ()),
            kb_db=(
                args.kb_db or os.environ.get("AGENTKERNEL_KB_DSN") or "~/.agentkernel/knowledge"
            ),
            kb_backend=args.kb_backend,
            mcp_profiles=tuple(args.mcp_profile or ()),
            mcp_profiles_file=args.mcp_profiles_file,
            raw_mcp_commands=tuple(args.mcp or ()),
            migrate=args.migrate,
        )

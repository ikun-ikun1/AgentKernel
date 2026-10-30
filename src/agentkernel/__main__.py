"""CLI 入口：python -m agentkernel。

实现已拆分到 cli/：
- cli/main.py         argparse、启动顺序、退出码、清理
- cli/repl.py         交互式命令与消息持久化
- cli/composition.py  工具/知识库/MCP 装配
- config/settings.py  类型化配置

本文件仅保留入口与旧测试使用的兼容别名；行为契约不变。
"""

from __future__ import annotations

from agentkernel.cli.composition import build_agent as _build_agent
from agentkernel.cli.composition import ingest_path as _ingest_path
from agentkernel.cli.main import _redact_dsn, main
from agentkernel.utils import env as env_utils

__all__ = ["_build_agent", "_ingest_path", "_redact_dsn", "env_utils", "main"]

if __name__ == "__main__":
    main()

"""保留期清理（P0-4b / G-13 备注）：删旧日志文件与旧 DB 行。

用法：
    python scripts/prune.py                       # 默认：日志 14 天，DB 90 天
    python scripts/prune.py --dry-run             # 只打印将删除什么
    python scripts/prune.py --log-dir ~/.agentkernel/logs --log-days 14 --db-days 90

约束：
- 只删 `*.jsonl` 与 messages/tool_logs 行，不删会话壳（/sessions 仍可见标题）。
- DB 不可用时只清理文件并给出警告（退出码 0），不静默失败。
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path


def prune_logs(log_dir: Path, days: int, dry_run: bool) -> list[Path]:
    if days < 0:
        raise ValueError("log-days 不能为负数")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed: list[Path] = []
    if not log_dir.exists():
        return removed
    for path in sorted(log_dir.glob("*.jsonl")):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            removed.append(path)
            if not dry_run:
                path.unlink()
    return removed


def prune_db(days: int, dsn: str | None, dry_run: bool) -> dict[str, int]:
    if days < 0:
        raise ValueError("db-days 不能为负数")
    from agentkernel.memory.factory import create_runtime_store

    store = create_runtime_store(dsn)
    try:
        if dry_run:
            return {"messages": -1, "tool_logs": -1}
        return store.prune_before(days)
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentKernel 保留期清理")
    parser.add_argument("--log-dir", default=None, help="JSONL 日志目录")
    parser.add_argument("--log-days", type=int, default=14, help="日志保留天数（默认 14）")
    parser.add_argument("--db-days", type=int, default=90, help="消息/工具日志保留天数（默认 90）")
    parser.add_argument("--dsn", default=None, help="DB DSN，默认读 AGENTKERNEL_DB_URL")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不删除")
    args = parser.parse_args()

    log_dir = Path(
        args.log_dir
        or (
            Path(os.environ["AGENTKERNEL_LOG"]).expanduser().parent
            if os.environ.get("AGENTKERNEL_LOG")
            else Path("~/.agentkernel/logs").expanduser()
        )
    )
    removed = prune_logs(log_dir, args.log_days, args.dry_run)
    print(
        f"日志：{log_dir} 早于 {args.log_days} 天："
        f"{len(removed)} 个文件{'(dry-run)' if args.dry_run else '已删除'}"
    )
    for path in removed:
        print(f"  - {path}")

    try:
        counts = prune_db(args.db_days, args.dsn, args.dry_run)
        print(
            f"DB：早于 {args.db_days} 天：messages={counts['messages']} "
            f"tool_logs={counts['tool_logs']}{'(dry-run)' if args.dry_run else ''}"
        )
    except Exception as exc:  # DB 不可用不应阻塞日志清理
        print(f"DB 清理跳过：{type(exc).__name__}: {str(exc)[:120]}")


if __name__ == "__main__":
    main()

"""一键体检（G-36）：python / .env / 依赖 / MySQL / 迁移 / 默认口令 / 磁盘。

用法：
    make doctor
    python scripts/doctor.py --dsn mysql+pymysql://user:***@127.0.0.1:3306/agentkernel
    python scripts/doctor.py --json

约定：
- 只读检查，不修改数据库与文件；任何输出都不打印 DSN 明文口令。
- MySQL 相关检查在未配置 MySQL DSN（sqlite 模式）时为 WARN，不算失败。
- 退出码：0 = 无 FAIL；1 = 有 FAIL；2 = `--strict` 且有 WARN。
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"
MIN_PYTHON = (3, 11)
DISK_WARN_BYTES = 1 * 1024**3
DISK_FAIL_BYTES = 200 * 1024**2
WEAK_PASSWORDS = {
    "",
    "password",
    "passwd",
    "123456",
    "root",
    "mysql",
    "admin",
    "changeme",
    "change-this-agent-password",
    "agentkernel",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # PASS / WARN / FAIL
    detail: str


def _redact_dsn(dsn: str) -> str:
    """把 DSN 中的口令替换为 ***，用于错误信息与外显。"""
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", dsn)


def check_python() -> CheckResult:
    version = sys.version_info
    text = f"{version.major}.{version.minor}.{version.micro}"
    if version[:2] >= MIN_PYTHON:
        return CheckResult("python", "PASS", f"{text}（要求 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）")
    return CheckResult(
        "python",
        "FAIL",
        f"{text} 低于要求 {MIN_PYTHON[0]}.{MIN_PYTHON[1]}；用 uv/pyenv 安装 3.11",
    )


def check_env_file(root: Path = PROJECT_ROOT) -> CheckResult:
    path = root / ".env"
    if not path.exists():
        return CheckResult(
            "env", "WARN", "未找到 .env；可 cp .env.example .env 并填 DSN/Key（或改用环境变量）"
        )
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return CheckResult(
            "env",
            "FAIL",
            f".env 权限 {mode:o} 允许组/其他用户读取；执行 chmod 600 .env",
        )
    return CheckResult("env", "PASS", f".env 存在，权限 {mode:o}")


def check_dependencies() -> CheckResult:
    required = {"openai": "openai", "dotenv": "python-dotenv"}
    mysql = {"sqlalchemy": "sqlalchemy", "pymysql": "pymysql", "alembic": "alembic"}
    missing_required = [
        pkg for mod, pkg in required.items() if importlib.util.find_spec(mod) is None
    ]
    missing_mysql = [pkg for mod, pkg in mysql.items() if importlib.util.find_spec(mod) is None]
    if missing_required:
        return CheckResult(
            "deps", "FAIL", f"缺少核心依赖：{', '.join(missing_required)}；执行 make sync"
        )
    if missing_mysql:
        return CheckResult(
            "deps",
            "WARN",
            f"缺少 MySQL 依赖：{', '.join(missing_mysql)}；执行 make sync（或只用 sqlite 模式）",
        )
    return CheckResult(
        "deps", "PASS", "核心 + MySQL 依赖已安装（openai/dotenv/sqlalchemy/pymysql/alembic）"
    )


def check_disk(log_file: str | None = None) -> CheckResult:
    raw = log_file or os.environ.get("AGENTKERNEL_LOG") or "~/.agentkernel/logs/agentkernel.jsonl"
    target = Path(raw).expanduser()
    probe = target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    free_gib = usage.free / 1024**3
    detail = f"{probe} 剩余 {free_gib:.2f} GiB"
    if usage.free < DISK_FAIL_BYTES:
        return CheckResult("disk", "FAIL", detail + "（< 200 MiB，日志/备份可能写失败）")
    if usage.free < DISK_WARN_BYTES:
        return CheckResult("disk", "WARN", detail + "（< 1 GiB，先 make prune 或清备份）")
    return CheckResult("disk", "PASS", detail)


def _is_mysql(dsn: str | None) -> bool:
    return bool(dsn) and (dsn.startswith("mysql://") or dsn.startswith("mysql+pymysql://"))


def _connect(dsn: str):
    from sqlalchemy import create_engine

    return create_engine(dsn, connect_args={"connect_timeout": 3}, pool_pre_ping=True)


def check_mysql(dsn: str | None) -> CheckResult:
    if not _is_mysql(dsn):
        return CheckResult("mysql", "WARN", "未配置 MySQL DSN（sqlite 模式），跳过连通性检查")
    try:
        engine = _connect(dsn)
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        engine.dispose()
    except Exception as exc:  # 体检必须把失败转成结果而不是栈
        return CheckResult(
            "mysql",
            "FAIL",
            f"连接失败：{type(exc).__name__}: {_redact_dsn(str(exc))[:300]}；"
            "检查 docker compose ps / 端口 3306 / DSN",
        )
    return CheckResult("mysql", "PASS", f"连接成功（{_redact_dsn(dsn)}）")


def migration_heads(versions_dir: Path = MIGRATIONS_DIR) -> set[str]:
    """从迁移脚本解析 revision 图，返回当前 head（无子节点的 revision）。"""
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if "revision" in names:
                revisions.add(str(ast.literal_eval(value)))
            if "down_revision" in names:
                literal = ast.literal_eval(value)
                if isinstance(literal, str):
                    parents.add(literal)
                elif isinstance(literal, (tuple, list)):
                    parents.update(str(item) for item in literal if item)
    return revisions - parents


def migration_verdict(current: str | None, heads: set[str]) -> CheckResult:
    if not heads:
        return CheckResult("migration", "FAIL", "未找到迁移脚本（migrations/versions/*.py）")
    ordered = ", ".join(sorted(heads))
    if not current:
        return CheckResult(
            "migration", "FAIL", f"alembic_version 为空；执行 --migrate（head: {ordered}）"
        )
    if current not in heads:
        return CheckResult(
            "migration",
            "FAIL",
            f"数据库版本 {current} != 代码 head {ordered}；执行 python -m agentkernel --migrate",
        )
    return CheckResult("migration", "PASS", f"数据库版本 {current} = head")


def check_migration(dsn: str | None) -> CheckResult:
    if not _is_mysql(dsn):
        return CheckResult("migration", "WARN", "未配置 MySQL DSN（sqlite 模式），跳过迁移版本检查")
    try:
        engine = _connect(dsn)
        with engine.connect() as conn:
            row = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
        engine.dispose()
    except Exception as exc:
        return CheckResult(
            "migration",
            "FAIL",
            f"读取 alembic_version 失败：{type(exc).__name__}: {_redact_dsn(str(exc))[:300]}",
        )
    return migration_verdict(str(row[0]) if row else None, migration_heads())


def check_default_password(dsn: str | None) -> CheckResult:
    if not _is_mysql(dsn):
        return CheckResult("password", "WARN", "未配置 MySQL DSN（sqlite 模式），跳过默认口令检查")
    try:
        from sqlalchemy.engine.url import make_url

        url = make_url(dsn)
        password = url.password or ""
    except Exception as exc:
        return CheckResult("password", "FAIL", f"DSN 无法解析：{type(exc).__name__}")
    if password.strip().lower() in WEAK_PASSWORDS:
        return CheckResult(
            "password", "FAIL", "DSN 使用默认/弱口令；更换强口令并同步 MYSQL_PASSWORD"
        )
    return CheckResult("password", "PASS", "DSN 口令非默认弱口令")


def run_checks(dsn: str | None, log_file: str | None = None) -> list[CheckResult]:
    return [
        check_python(),
        check_env_file(),
        check_dependencies(),
        check_mysql(dsn),
        check_migration(dsn),
        check_default_password(dsn),
        check_disk(log_file),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentKernel 一键体检（7 项）")
    parser.add_argument(
        "--dsn",
        default=None,
        help="MySQL DSN；默认读 AGENTKERNEL_DB_URL（不传则只检查 sqlite/本地环境）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON（供 CI/脚本消费）")
    parser.add_argument("--strict", action="store_true", help="WARN 也返回非零（退出码 2）")
    parser.add_argument("--log", default=None, help="日志文件路径（用于磁盘余量探测）")
    args = parser.parse_args(argv)

    from agentkernel.utils import env as env_utils

    env_utils.load_env()
    dsn = args.dsn or os.environ.get("AGENTKERNEL_DB_URL")
    results = run_checks(dsn, args.log)
    counts = {
        status: sum(1 for r in results if r.status == status) for status in ("PASS", "WARN", "FAIL")
    }

    if args.json:
        print(
            json.dumps(
                {
                    "ok": counts["FAIL"] == 0,
                    "counts": counts,
                    "checks": [asdict(r) for r in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"AgentKernel doctor（{len(results)} 项）")
        for result in results:
            print(f"[{result.status}] {result.name:<9} {result.detail}")
        print(f"结果：{counts['PASS']} PASS / {counts['WARN']} WARN / {counts['FAIL']} FAIL")

    if counts["FAIL"]:
        return 1
    if args.strict and counts["WARN"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

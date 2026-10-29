"""MySQL 逻辑备份（G-17）。

用法：
    python scripts/backup.py                 # 读 AGENTKERNEL_DB_URL / .env，保留 7 份
    python scripts/backup.py --out-dir backups --keep 7
    python scripts/backup.py --via docker --container agentkernel-mysql

约定：
- mysqldump --single-transaction 生成 InnoDB 一致性快照；
- 口令只经 MYSQL_PWD 环境变量传递（docker exec -e VAR 转发），不出现在 argv/日志；
- 产物：`agentkernel-YYYYmmdd-HHMMSS.sql.gz` + 同名 `.sha256`；按 mtime 只保留最近 N 份。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_CONTAINER = "agentkernel-mysql"


def load_dsn(explicit: str | None) -> str:
    if explicit:
        return explicit
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from agentkernel.utils import env

    env.load_env()
    dsn = os.environ.get("AGENTKERNEL_DB_URL")
    if not dsn:
        raise SystemExit("缺少 AGENTKERNEL_DB_URL（或传 --dsn）")
    return dsn


def parse_dsn(dsn: str) -> dict[str, object]:
    parsed = urlparse(dsn)
    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise SystemExit("只支持 mysql+pymysql:// DSN")
    database = parsed.path.lstrip("/")
    if not database:
        raise SystemExit("DSN 缺少数据库名")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
    }


def choose_via(explicit: str) -> str:
    if explicit != "auto":
        return explicit
    return "local" if shutil.which("mysqldump") else "docker"


def dump_command(info: dict[str, object], via: str, container: str) -> list[str]:
    common = [
        "--single-transaction",
        "--quick",
        "--routines",
        "--no-tablespaces",
        "--default-character-set=utf8mb4",
        # 不加 --databases：避免备份里带 CREATE DATABASE/USE，恢复演练才能安全导入临时库
        str(info["database"]),
    ]
    if via == "docker":
        return [
            "docker",
            "exec",
            "-i",
            "-e",
            "MYSQL_PWD",
            container,
            "/usr/bin/mysqldump",
            "-h",
            "127.0.0.1",
            "-P",
            "3306",
            "-u",
            str(info["user"]),
            *common,
        ]
    return [
        "mysqldump",
        "-h",
        str(info["host"]),
        "-P",
        str(info["port"]),
        "-u",
        str(info["user"]),
        *common,
    ]


def prune(out_dir: Path, keep: int) -> list[Path]:
    backups = sorted(out_dir.glob("agentkernel-*.sql.gz"), key=lambda p: p.stat().st_mtime)
    removed: list[Path] = []
    for path in backups[:-keep] if keep > 0 else []:
        removed.append(path)
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".sha256").unlink(missing_ok=True)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="MySQL 逻辑备份")
    parser.add_argument("--dsn", default=None, help="默认读 AGENTKERNEL_DB_URL")
    parser.add_argument("--out-dir", default="backups", help="备份目录（默认 backups）")
    parser.add_argument("--keep", type=int, default=7, help="保留份数（默认 7）")
    parser.add_argument("--via", choices=("auto", "local", "docker"), default="auto")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    args = parser.parse_args()

    info = parse_dsn(load_dsn(args.dsn))
    via = choose_via(args.via)
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(UTC)
    proc = subprocess.run(
        dump_command(info, via, args.container),
        capture_output=True,
        env={**os.environ, "MYSQL_PWD": str(info["password"])},
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"mysqldump 失败（exit={proc.returncode}）：{proc.stderr.decode()[:300]}")

    stamp = started.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"agentkernel-{stamp}.sql.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(proc.stdout)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )

    removed = prune(out_dir, args.keep)
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"备份完成：{path}（{size_mb:.2f} MB，sha256={digest[:16]}…，via={via}）")
    if removed:
        print(f"按保留份数 {args.keep} 清理：{len(removed)} 个旧备份")


if __name__ == "__main__":
    main()

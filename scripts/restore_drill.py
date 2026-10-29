"""恢复演练（G-18）：把最近备份恢复到临时库，校验行数、计时并输出报告。

用法：
    python scripts/restore_drill.py                 # 用 backups/ 里最新备份
    python scripts/restore_drill.py --backup backups/agentkernel-XXXX.sql.gz
    python scripts/restore_drill.py --keep-tmp      # 演练后保留临时库（排查用）

约束：
- 创建/授权/删除临时库需要管理员权限（默认 root，口令读 `MYSQL_ROOT_PASSWORD`）；
- 恢复与校验使用应用账号（验证应用账号确实能读回恢复后的数据）；
- 报告写到 `docs/reports/restore-drill-YYYYMMDD.md`，含行数对比、耗时、RPO/RTO 判定。
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

TABLES = ("sessions", "messages", "tool_logs", "documents", "chunks")
RTO_SECONDS = 30 * 60
RPO_HOURS = 24


def assert_dump_is_single_db(payload: bytes, source_db: str) -> None:
    """防呆：备份里不得出现 CREATE DATABASE / USE 源库，否则恢复会写回源库。"""
    text = payload.decode("utf-8", errors="replace")
    if "CREATE DATABASE" in text or f"USE `{source_db}`" in text:
        raise SystemExit(
            "备份包含 CREATE DATABASE/USE 语句，拒绝恢复（请用不带 --databases 的 mysqldump 重新备份）"
        )


def _bootstrap() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _load_dsn(explicit: str | None) -> str:
    if explicit:
        return explicit
    _bootstrap()
    from agentkernel.utils import env

    env.load_env()
    dsn = os.environ.get("AGENTKERNEL_DB_URL")
    if not dsn:
        raise SystemExit("缺少 AGENTKERNEL_DB_URL（或传 --dsn）")
    return dsn


def _parse(dsn: str) -> dict[str, object]:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(dsn)
    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise SystemExit("只支持 mysql+pymysql:// DSN")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
    }


def _choose_via(explicit: str) -> str:
    if explicit != "auto":
        return explicit
    return "local" if shutil.which("mysql") else "docker"


def _docker(
    container: str, user: str, password: str, args: list[str], *, stdin: bytes | None = None
):
    return subprocess.run(
        ["docker", "exec", "-i", "-e", "MYSQL_PWD", container, "/usr/bin/mysql", "-u", user, *args],
        input=stdin,
        capture_output=True,
        env={**os.environ, "MYSQL_PWD": password},
        check=False,
    )


def _local(
    info: dict[str, object],
    user: str,
    password: str,
    args: list[str],
    *,
    stdin: bytes | None = None,
):
    return subprocess.run(
        [
            "mysql",
            "-h",
            str(info["host"]),
            "-P",
            str(info["port"]),
            "-u",
            user,
            *args,
        ],
        input=stdin,
        capture_output=True,
        env={**os.environ, "MYSQL_PWD": password},
        check=False,
    )


def _client(
    via: str,
    info: dict[str, object],
    container: str,
    user: str,
    password: str,
    args: list[str],
    *,
    stdin: bytes | None = None,
):
    if via == "docker":
        return _docker(container, user, password, ["-h", "127.0.0.1", *args], stdin=stdin)
    return _local(info, user, password, args, stdin=stdin)


def _counts(dsn_info: dict[str, object], database: str, password: str) -> dict[str, int | None]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    url = URL.create(
        "mysql+pymysql",
        username=str(dsn_info["user"]),
        password=password,
        host=str(dsn_info["host"]),
        port=int(dsn_info["port"]),
        database=database,
    )
    engine = create_engine(url, pool_pre_ping=True, future=True)
    counts: dict[str, int | None] = {}
    try:
        with engine.connect() as conn:
            for table in TABLES:
                try:
                    counts[table] = int(
                        conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar_one()
                    )
                except Exception:
                    counts[table] = None
    finally:
        engine.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="MySQL 恢复演练")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--backup", default=None, help="备份文件；默认取最新")
    parser.add_argument("--backup-dir", default="backups")
    parser.add_argument("--tmp-db", default="agentkernel_restore_drill")
    parser.add_argument("--out", default="docs/reports")
    parser.add_argument("--via", choices=("auto", "local", "docker"), default="auto")
    parser.add_argument("--container", default="agentkernel-mysql")
    parser.add_argument("--admin-user", default="root")
    parser.add_argument("--keep-tmp", action="store_true")
    args = parser.parse_args()

    info = _parse(_load_dsn(args.dsn))
    via = _choose_via(args.via)
    password = str(info["password"])
    admin_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if not admin_password:
        raise SystemExit("缺少 MYSQL_ROOT_PASSWORD（创建/删除临时库需要管理员权限）")

    if args.backup:
        backup = Path(args.backup)
    else:
        candidates = sorted(
            Path(args.backup_dir).glob("agentkernel-*.sql.gz"), key=lambda p: p.stat().st_mtime
        )
        if not candidates:
            raise SystemExit(f"{args.backup_dir} 下没有备份，先跑 make backup")
        backup = candidates[-1]
    if not backup.exists():
        raise SystemExit(f"备份不存在：{backup}")

    age_hours = (datetime.now(UTC).timestamp() - backup.stat().st_mtime) / 3600
    tmp_db = args.tmp_db
    admin = lambda sql: _client(
        via, info, args.container, args.admin_user, admin_password, ["-e", sql]
    )
    started = time.monotonic()
    try:
        result = admin(
            f"DROP DATABASE IF EXISTS `{tmp_db}`; CREATE DATABASE `{tmp_db}` CHARACTER SET utf8mb4;"
        )
        if result.returncode != 0:
            raise SystemExit(f"创建临时库失败：{result.stderr.decode()[:300]}")
        result = admin(f"GRANT ALL ON `{tmp_db}`.* TO '{info['user']}'@'%';")
        if result.returncode != 0:
            raise SystemExit(f"授权临时库失败：{result.stderr.decode()[:300]}")

        payload = gzip.decompress(backup.read_bytes())
        assert_dump_is_single_db(payload, str(info["database"]))
        restore = _client(
            via, info, args.container, str(info["user"]), password, [tmp_db], stdin=payload
        )
        if restore.returncode != 0:
            raise SystemExit(f"恢复失败：{restore.stderr.decode()[:300]}")
        restore_seconds = time.monotonic() - started

        source = _counts(info, str(info["database"]), password)
        restored = _counts(info, tmp_db, password)
        mismatched = {
            table: (source[table], restored[table])
            for table in TABLES
            if source[table] is not None and source[table] != restored[table]
        }
        verdict = "PASS" if not mismatched and restore_seconds <= RTO_SECONDS else "FAIL"

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        report = out_dir / f"restore-drill-{datetime.now(UTC).strftime('%Y%m%d')}.md"
        rows = "\n".join(
            f"| {table} | {source[table] if source[table] is not None else 'n/a'} | "
            f"{restored[table] if restored[table] is not None else 'n/a'} | "
            f"{'OK' if source[table] == restored[table] else 'MISMATCH'} |"
            for table in TABLES
        )
        report.write_text(
            f"""# 恢复演练报告 · {datetime.now(UTC).strftime("%Y-%m-%d")}

- 结论：**{verdict}**
- 备份文件：`{backup}`（{backup.stat().st_size / 1024 / 1024:.2f} MB，age={age_hours:.1f}h）
- 临时库：`{tmp_db}`（演练后{"保留" if args.keep_tmp else "删除"}）
- 恢复耗时：**{restore_seconds:.1f}s**（RTO 目标 ≤ {RTO_SECONDS}s）
- 备份年龄：**{age_hours:.1f}h**（RPO 目标 ≤ {RPO_HOURS}h）
- 执行方式：{via}；应用账号：{info["user"]}

| 表 | 源库 | 恢复库 | 结果 |
|---|---|---|---|
{rows}

> 由 `make restore-drill` 生成；口径见 docs/production-standard.md §4.3。
""",
            encoding="utf-8",
        )
        print(f"演练 {verdict}：恢复 {restore_seconds:.1f}s，报告 {report}")
        if mismatched:
            print(f"行数不一致：{mismatched}")
            sys.exit(1)
        if restore_seconds > RTO_SECONDS:
            print(f"超过 RTO 目标 {RTO_SECONDS}s")
            sys.exit(1)
    finally:
        if not args.keep_tmp:
            admin(f"DROP DATABASE IF EXISTS `{tmp_db}`;")


if __name__ == "__main__":
    main()

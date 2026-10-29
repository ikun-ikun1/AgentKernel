"""备份/恢复演练脚本的纯函数测试（G-17/G-18）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


backup = _load("ak_backup", "backup.py")
drill = _load("ak_restore_drill", "restore_drill.py")


def test_parse_dsn_handles_special_chars() -> None:
    info = backup.parse_dsn("mysql+pymysql://u%40ser:p%23w@db.local:3307/agentkernel")
    assert info["user"] == "u@ser"
    assert info["password"] == "p#w"
    assert info["database"] == "agentkernel"
    assert info["port"] == 3307


def test_dump_command_is_single_database() -> None:
    info = {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "u",
        "password": "p",
        "database": "agentkernel",
    }
    cmd = backup.dump_command(info, "local", "c")
    assert "--databases" not in cmd
    assert cmd[-1] == "agentkernel"


def test_drill_rejects_dump_with_create_database() -> None:
    payload = b"CREATE DATABASE agentkernel;\nUSE `agentkernel`;\n"
    with pytest.raises(SystemExit, match="拒绝恢复"):
        drill.assert_dump_is_single_db(payload, "agentkernel")


def test_drill_accepts_single_db_dump() -> None:
    payload = b"DROP TABLE IF EXISTS `messages`;\nCREATE TABLE `messages` (id INT);\n"
    drill.assert_dump_is_single_db(payload, "agentkernel")


def test_prune_keeps_newest(tmp_path: Path) -> None:
    import os
    import time

    for index in range(4):
        path = tmp_path / f"agentkernel-2026010{index}.sql.gz"
        path.write_bytes(b"x")
        path.with_suffix(path.suffix + ".sha256").write_text("h", encoding="utf-8")
        os.utime(path, (time.time() + index, time.time() + index))
    removed = backup.prune(tmp_path, keep=2)
    assert [p.name for p in removed] == [
        "agentkernel-20260100.sql.gz",
        "agentkernel-20260101.sql.gz",
    ]
    assert len(list(tmp_path.glob("agentkernel-*.sql.gz"))) == 2
    assert not (tmp_path / "agentkernel-20260100.sql.gz.sha256").exists()

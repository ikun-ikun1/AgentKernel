"""迁移往返测试（P1/G-15）：upgrade → downgrade base → upgrade。

CI 提供 `AGENTKERNEL_MYSQL_TEST_DSN` 时真跑；本地无 DSN 时跳过（CI 要求 0 skip）。
测试会清空目标测试库里的表，只允许对专用测试库执行。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("AGENTKERNEL_MYSQL_TEST_DSN"),
    reason="未配置 AGENTKERNEL_MYSQL_TEST_DSN",
)

REPO = Path(__file__).resolve().parents[1]


def _config():
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "migrations"))
    return cfg


def _reset(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        rows = conn.execute(text("SHOW TABLES")).fetchall()
        for (table,) in rows:
            conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def test_upgrade_downgrade_roundtrip() -> None:
    from alembic import command
    from sqlalchemy import create_engine, inspect

    dsn = os.environ["AGENTKERNEL_MYSQL_TEST_DSN"]
    os.environ["AGENTKERNEL_DB_URL"] = dsn
    engine = create_engine(dsn, future=True)
    _reset(engine)
    try:
        command.upgrade(_config(), "head")
        columns = {col["name"] for col in inspect(engine).get_columns("tool_logs")}
        assert "duration_ms" in columns

        command.downgrade(_config(), "base")
        assert "tool_logs" not in inspect(engine).get_table_names()

        command.upgrade(_config(), "head")
        columns = {col["name"] for col in inspect(engine).get_columns("tool_logs")}
        assert "duration_ms" in columns
    finally:
        engine.dispose()

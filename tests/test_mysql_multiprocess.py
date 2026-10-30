"""D4 失败复现：多进程并发写同一会话（PR 1，不改生产代码）。

实现见 ADR-002：写事务内先 SELECT ... FOR UPDATE 锁会话行，再写消息并更新 updated_at。
CI 提供 AGENTKERNEL_MYSQL_TEST_DSN 时真跑（0 skip）。

三条不变量：
1. 无 worker 异常退出；
2. 消息数 = 进程数 × 每进程写次数（无丢失/重复）；
3. sessions.updated_at == max(messages.created_at)（时间不回退）。
"""

from __future__ import annotations

import multiprocessing as mp
import os
from pathlib import Path

import pytest

DSN = os.environ.get("AGENTKERNEL_MYSQL_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="未配置 AGENTKERNEL_MYSQL_TEST_DSN")


def _migrate_schema() -> None:
    """G-16：集成测试也走 Alembic，不再依赖 create_all。"""
    from alembic import command
    from alembic.config import Config

    repo = Path(__file__).resolve().parents[1]
    os.environ["AGENTKERNEL_DB_URL"] = DSN
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _migrate_schema()


SESSION_ID = "d4-mp-session"
PROCESSES = 20
WRITES_PER_PROCESS = 20


def _worker(barrier, index: int) -> None:
    from agentkernel.memory.factory import create_runtime_store

    store = create_runtime_store(DSN)
    try:
        barrier.wait(timeout=30)
        for j in range(WRITES_PER_PROCESS):
            store.append_message(SESSION_ID, "user", f"{index}-{j}")
    finally:
        store.close()


def test_multiprocess_same_session_consistency() -> None:
    from sqlalchemy import text

    from agentkernel.memory.factory import create_runtime_store

    store = create_runtime_store(DSN)
    try:
        store.delete_session(SESSION_ID)
        store.create_session(SESSION_ID)

        ctx = mp.get_context("fork")
        barrier = ctx.Barrier(PROCESSES)
        procs = [ctx.Process(target=_worker, args=(barrier, i)) for i in range(PROCESSES)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=180)

        assert [p.exitcode for p in procs if p.exitcode != 0] == [], "worker 异常退出"

        with store.engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM messages WHERE session_id = :s"),
                {"s": SESSION_ID},
            ).scalar_one()
            updated = conn.execute(
                text("SELECT updated_at FROM sessions WHERE id = :s"), {"s": SESSION_ID}
            ).scalar_one()
            latest = conn.execute(
                text("SELECT MAX(created_at) FROM messages WHERE session_id = :s"),
                {"s": SESSION_ID},
            ).scalar_one()
        assert count == PROCESSES * WRITES_PER_PROCESS, f"消息数={count}"
        assert updated == latest, f"updated_at={updated} 早于最后一条消息 {latest}"
    finally:
        store.close()

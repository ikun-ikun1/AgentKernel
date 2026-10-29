"""D4 失败复现：多进程并发写同一会话（PR 1，不改生产代码）。

当前实现只有进程内 per-session 锁，跨进程无效；本用例预期失败，
用 xfail(strict=True) 记录，PR 2（行锁串行化）移除 xfail 并转绿。
CI 提供 AGENTKERNEL_MYSQL_TEST_DSN 时真跑（0 skip）。

三条不变量：
1. 无 worker 异常退出；
2. 消息数 = 进程数 × 每进程写次数（无丢失/重复）；
3. sessions.updated_at == max(messages.created_at)（时间不回退）。
"""

from __future__ import annotations

import multiprocessing as mp
import os

import pytest

DSN = os.environ.get("AGENTKERNEL_MYSQL_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="未配置 AGENTKERNEL_MYSQL_TEST_DSN")

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


@pytest.mark.xfail(
    strict=True,
    reason="D4 未实现：进程内锁跨进程无效，updated_at 可能早于最后一条消息",
)
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
        assert store.count_messages(SESSION_ID) == PROCESSES * WRITES_PER_PROCESS

        with store.engine.connect() as conn:
            updated = conn.execute(
                text("SELECT updated_at FROM sessions WHERE id = :s"), {"s": SESSION_ID}
            ).scalar_one()
            latest = conn.execute(
                text("SELECT MAX(created_at) FROM messages WHERE session_id = :s"),
                {"s": SESSION_ID},
            ).scalar_one()
        assert updated == latest, f"updated_at={updated} 早于最后一条消息 {latest}"
    finally:
        store.close()

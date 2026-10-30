"""MySQL 集成测试（ADR-001）。

仅当设置 `AGENTKERNEL_MYSQL_TEST_DSN` 时运行，且测试库应为独立实例。
用法示例：
    AGENTKERNEL_MYSQL_TEST_DSN=mysql+pymysql://agentkernel:change-me@127.0.0.1:3306/agentkernel_test pytest -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

MYSQL_TEST_DSN = os.environ.get("AGENTKERNEL_MYSQL_TEST_DSN")

pytestmark = pytest.mark.skipif(not MYSQL_TEST_DSN, reason="未配置 AGENTKERNEL_MYSQL_TEST_DSN")


def _migrate_schema() -> None:
    """G-16：集成测试也走 Alembic，不再依赖 create_all。"""
    from alembic import command
    from alembic.config import Config

    repo = Path(__file__).resolve().parents[1]
    os.environ["AGENTKERNEL_DB_URL"] = MYSQL_TEST_DSN
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _migrate_schema()


@pytest.fixture()
def mysql_runtime_store():
    from agentkernel.memory.mysql_store import MySQLRuntimeStore

    store = MySQLRuntimeStore(MYSQL_TEST_DSN)
    store.ensure_schema()
    yield store
    store.close()


@pytest.fixture()
def mysql_knowledge_store():
    from agentkernel.rag.mysql_store import MySQLKnowledgeStore

    store = MySQLKnowledgeStore(MYSQL_TEST_DSN)
    store.ensure_schema()
    yield store
    store.close()


def test_runtime_roundtrip(mysql_runtime_store):
    store = mysql_runtime_store
    store.delete_session("it-session")
    store.create_session("it-session", "集成测试")
    store.append_message("it-session", "user", "hello")
    store.append_message("it-session", "assistant", "hi")
    msgs = store.get_messages("it-session")
    assert [m["role"] for m in msgs] == ["user", "assistant"]

    store.log_tool_call("it-session", "calculator", {"expression": "1+2"}, "3", True)
    logs = store.list_tool_logs("it-session")
    assert logs and logs[0]["tool_name"] == "calculator"


def test_knowledge_roundtrip_and_lexical(mysql_knowledge_store):
    from agentkernel.rag.ingest import Chunk

    store = mysql_knowledge_store
    doc_id = "it-doc-1"
    store.upsert_document(
        {
            "doc_id": doc_id,
            "doc_name": "it.md",
            "source": "it.md",
            "checksum": "abc",
            "size_bytes": 10,
            "modified_at": 0.0,
            "ingested_at": "2026-09-01T00:00:00+00:00",
            "chunk_count": 1,
        },
        [
            Chunk(
                chunk_id=f"{doc_id}:0",
                doc_name="it.md",
                text="AgentKernel 从零实现 ReAct 主循环，使用 MySQL ngram 检索。",
                metadata={"ordinal": 0},
                source="it.md",
            )
        ],
    )
    assert store.get_document(doc_id) is not None
    results = store.lexical_query("ReAct 主循环", limit=5)
    assert results
    assert "来源" in results[0].to_citation()
    assert store.delete_document(doc_id) is True


def test_concurrent_message_writes(mysql_runtime_store):
    """同一会话并发写消息不应出现死锁或丢失（回归测试）。"""
    import threading

    store = mysql_runtime_store
    store.create_session("it-concurrent", "并发写入")
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            store.append_message("it-concurrent", "user", f"msg-{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"并发写入出现异常: {errors}"
    messages = store.get_messages("it-concurrent")
    assert len(messages) >= 20

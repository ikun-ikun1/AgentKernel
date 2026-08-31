"""MySQL 集成测试（ADR-001）。

仅当设置 `AGENTKERNEL_MYSQL_TEST_DSN` 时运行，且测试库应为独立实例。
用法示例：
    AGENTKERNEL_MYSQL_TEST_DSN=mysql+pymysql://agentkernel:agentkernel@127.0.0.1:3306/agentkernel_test pytest -q
"""
from __future__ import annotations

import os

import pytest

MYSQL_TEST_DSN = os.environ.get("AGENTKERNEL_MYSQL_TEST_DSN")

pytestmark = pytest.mark.skipif(not MYSQL_TEST_DSN, reason="未配置 AGENTKERNEL_MYSQL_TEST_DSN")


@pytest.fixture()
def mysql_runtime_store():
    from agentkernel.memory.mysql_store import MySQLRuntimeStore

    store = MySQLRuntimeStore(MYSQL_TEST_DSN)
    store._ensure_tables()
    yield store
    store.close()


@pytest.fixture()
def mysql_knowledge_store():
    from agentkernel.rag.mysql_store import MySQLKnowledgeStore

    store = MySQLKnowledgeStore(MYSQL_TEST_DSN)
    store.ensure_tables()
    yield store
    store.close()


def test_runtime_roundtrip(mysql_runtime_store):
    store = mysql_runtime_store
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

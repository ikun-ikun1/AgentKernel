"""SQLite 记忆模块测试（标准库 sqlite3，无需外部依赖）。"""
from __future__ import annotations

from agentkernel.memory.sqlite_store import SQLiteStore


def test_append_and_get_messages():
    with SQLiteStore(":memory:") as store:
        store.create_session("s1")
        store.append_message("s1", "user", "你好")
        store.append_message("s1", "assistant", "你好，我叫 AgentKernel")
        msgs = store.get_messages("s1")
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["content"] == "你好，我叫 AgentKernel"


def test_sessions_sorted_by_activity():
    with SQLiteStore(":memory:") as store:
        store.create_session("old")
        store.create_session("new")
        store.append_message("old", "user", "x")
        store.append_message("new", "user", "y")
        sessions = store.list_sessions()
        assert [s["id"] for s in sessions] == ["new", "old"]


def test_delete_session_cascades():
    with SQLiteStore(":memory:") as store:
        store.create_session("s1")
        store.append_message("s1", "user", "hello")
        store.delete_session("s1")
        assert store.get_messages("s1") == []
        assert store.list_sessions() == []


def test_limit_and_offset():
    with SQLiteStore(":memory:") as store:
        store.create_session("s1")
        for i in range(5):
            store.append_message("s1", "user", f"m{i}")
        assert [m["content"] for m in store.get_messages("s1", limit=2)] == ["m0", "m1"]
        assert [m["content"] for m in store.get_messages("s1", limit=2, offset=1)] == [
            "m1",
            "m2",
        ]

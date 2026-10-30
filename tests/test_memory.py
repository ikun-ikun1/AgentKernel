"""Runtime 存储测试：SQLite 测试适配器 + 工厂选择。"""

from __future__ import annotations

from agentkernel.adapters.memory.sqlite_store import SQLiteStore
from agentkernel.memory.factory import create_runtime_store


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


def test_tool_logs_audit():
    with SQLiteStore(":memory:") as store:
        store.create_session("s1")
        store.log_tool_call("s1", "calculator", {"expression": "1+2"}, "3", success=True)
        store.log_tool_call("s1", "nope", {}, "[工具不存在] 未注册的工具：nope", success=False)
        logs = store.list_tool_logs("s1")
        assert len(logs) == 2
        # 按时间倒序，最近的在前面
        assert logs[0]["tool_name"] == "nope"
        assert logs[1]["tool_name"] == "calculator"
        assert logs[1]["success"] == 1
        assert logs[0]["success"] == 0


def test_factory_creates_sqlite_store_for_memory_dsn():
    store = create_runtime_store(":memory:")
    assert isinstance(store, SQLiteStore)
    store.close()


def test_factory_creates_sqlite_store_for_path(tmp_path):
    store = create_runtime_store(str(tmp_path / "runtime.db"))
    assert isinstance(store, SQLiteStore)
    store.close()

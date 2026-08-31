"""Runtime 持久化接口（ADR-001）。

Runtime 只依赖本模块定义的 Store 接口，不直接 import SQLite/MySQL 驱动。
生产主存储为 MySQL，SQLite 仅作为测试与本地无 MySQL 时的适配器。
"""
from __future__ import annotations

from typing import Protocol


class RuntimeStore(Protocol):
    """会话、消息与工具调用审计的最小持久化接口。"""

    def create_session(self, session_id: str, title: str = "") -> str:
        """创建会话；已存在时忽略。"""
        ...

    def list_sessions(self, limit: int = 20) -> list[dict[str, str]]:
        """按最近活跃顺序返回会话列表。"""
        ...

    def delete_session(self, session_id: str) -> None:
        """删除会话及其关联消息/工具日志。"""
        ...

    def append_message(self, session_id: str, role: str, content: str) -> int:
        """追加一条消息并更新会话活跃时间。"""
        ...

    def get_messages(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, str]]:
        """按插入顺序返回会话消息。"""
        ...

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        action_input: dict[str, object],
        result: str,
        success: bool,
    ) -> int:
        """写入一条工具调用审计记录。"""
        ...

    def list_tool_logs(self, session_id: str, limit: int = 20) -> list[dict[str, object]]:
        """按时间倒序返回工具调用日志。"""
        ...

    def close(self) -> None:
        """关闭连接/连接池。"""
        ...

"""MySQL Runtime 主存储（ADR-001）。

使用 SQLAlchemy 2.x Core + PyMySQL，通过连接池与显式事务边界访问 MySQL。
依赖未安装或连接失败时抛出明确错误；CLI/工厂负责给出降级提示。
"""

from __future__ import annotations

import random
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from agentkernel.memory.base import RuntimeStore
from agentkernel.utils.errors import AgentKernelError
from agentkernel.utils.observability import redact, truncate


class MySQLStoreError(AgentKernelError):
    """MySQL 持久化错误。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_deadlock(exc: Exception) -> bool:
    """MySQL 1213 死锁 / 1205 锁等待超时：生产写入应重试。"""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", (None,)) if orig is not None else (None,)
    return bool(args) and args[0] in (1213, 1205)


class MySQLRuntimeStore(RuntimeStore):
    """MySQL 8 会话/消息/工具日志存储。"""

    def __init__(self, dsn: str) -> None:
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.exc import SQLAlchemyError
        except ImportError as exc:
            raise MySQLStoreError(
                "MySQL 主存储需要 SQLAlchemy/PyMySQL：pip install -e '.[mysql]'"
            ) from exc

        self.dsn = dsn
        self._create_engine = create_engine
        self._text = text
        self._sqlalchemy_error = SQLAlchemyError
        self._engine: Any = None
        self._session_locks: dict[str, threading.Lock] = {}
        self._session_locks_guard = threading.Lock()

    def _session_lock(self, session_id: str) -> threading.Lock:
        """同一会话的写操作在本进程内串行，避免并发 UPDATE 同一行导致死锁。"""
        with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_id] = lock
            return lock

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = self._create_engine(
                self.dsn,
                pool_pre_ping=True,
                pool_recycle=3600,
                future=True,
            )
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _ensure_tables(self) -> None:
        """ADR-001 要求 Alembic 管理迁移；这里仅做开发兜底。"""
        try:
            from sqlalchemy import (
                Column,
                Float,
                ForeignKey,
                Index,
                Integer,
                MetaData,
                String,
                Table,
                Text,
            )
        except ImportError as exc:
            raise MySQLStoreError(
                "MySQL 主存储需要 SQLAlchemy/PyMySQL：pip install -e '.[mysql]'"
            ) from exc

        metadata = MetaData()
        Table(
            "sessions",
            metadata,
            Column("id", String(64), primary_key=True),
            Column("title", String(255), nullable=False, server_default=""),
            Column("created_at", String(64), nullable=False),
            Column("updated_at", String(64), nullable=False),
        )
        Table(
            "messages",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "session_id",
                String(64),
                ForeignKey("sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("role", String(32), nullable=False),
            Column("content", Text, nullable=False),
            Column("created_at", String(64), nullable=False),
        )
        Table(
            "tool_logs",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column(
                "session_id",
                String(64),
                ForeignKey("sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("tool_name", String(128), nullable=False),
            Column("input_json", Text, nullable=False),
            Column("output_json", Text, nullable=False),
            Column("success", Integer, nullable=False, server_default="1"),
            Column("duration_ms", Float(), nullable=True),
            Column("created_at", String(64), nullable=False),
        )
        Index("idx_messages_session_id", metadata.tables["messages"].c.session_id)
        Index("idx_tool_logs_session_id", metadata.tables["tool_logs"].c.session_id)
        metadata.create_all(self.engine)
        # 向前兼容：老库已存在 tool_logs 但没有 duration_ms 时补列（与迁移 0002 等价）。
        # 这是 G-16「DDL 双轨」的过渡措施；最终收口是只走 Alembic。
        try:
            from sqlalchemy import inspect, text
        except ImportError:  # pragma: no cover - 上面已保证可导入
            return
        with self.engine.begin() as conn:
            columns = {col["name"] for col in inspect(conn).get_columns("tool_logs")}
            if "duration_ms" not in columns:
                conn.execute(text("ALTER TABLE tool_logs ADD COLUMN duration_ms FLOAT NULL"))

    # ---- 会话 ----

    def create_session(self, session_id: str, title: str = "") -> str:
        now = _now()
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT IGNORE INTO sessions (id, title, created_at, updated_at) "
                    "VALUES (:id, :title, :created_at, :updated_at)"
                ),
                {
                    "id": session_id,
                    "title": title or session_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return session_id

    def list_sessions(self, limit: int = 20) -> list[dict[str, str]]:
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, title, created_at, updated_at FROM sessions "
                    "ORDER BY updated_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings()
        return [dict(row) for row in rows]

    def delete_session(self, session_id: str) -> None:
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": session_id})

    def append_message(self, session_id: str, role: str, content: str) -> int:
        now = _now()
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import OperationalError
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        last_exc: Exception | None = None
        with self._session_lock(session_id):
            for attempt in range(3):
                try:
                    with self.engine.begin() as conn:
                        cursor = conn.execute(
                            text(
                                "INSERT INTO messages (session_id, role, content, created_at) "
                                "VALUES (:session_id, :role, :content, :created_at)"
                            ),
                            {
                                "session_id": session_id,
                                "role": role,
                                "content": content,
                                "created_at": now,
                            },
                        )
                        conn.execute(
                            text("UPDATE sessions SET updated_at = :now WHERE id = :id"),
                            {"now": now, "id": session_id},
                        )
                        return int(cursor.lastrowid or 0)
                except OperationalError as exc:
                    if _is_deadlock(exc) and attempt < 2:
                        last_exc = exc
                        time.sleep(0.05 * (attempt + 1) + random.random() * 0.05)
                        continue
                    raise
        assert last_exc is not None
        raise last_exc

    def get_messages(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, str]]:
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        sql = (
            "SELECT role, content FROM messages WHERE session_id = :session_id "
            "ORDER BY id ASC LIMIT :limit OFFSET :offset"
        )
        params: dict[str, Any] = {
            "session_id": session_id,
            "limit": limit if limit is not None else 2**31 - 1,
            "offset": offset,
        }
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings()
        return [dict(row) for row in rows]

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        action_input: dict[str, object],
        result: str,
        success: bool,
        duration_ms: float | None = None,
    ) -> int:
        import json as _json

        now = _now()
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import OperationalError
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        last_exc: Exception | None = None
        with self._session_lock(session_id):
            for attempt in range(3):
                try:
                    with self.engine.begin() as conn:
                        cursor = conn.execute(
                            text(
                                "INSERT INTO tool_logs "
                                "(session_id, tool_name, input_json, output_json, success, "
                                "duration_ms, created_at) "
                                "VALUES (:session_id, :tool_name, :input_json, :output_json, "
                                ":success, :duration_ms, :created_at)"
                            ),
                            {
                                "session_id": session_id,
                                "tool_name": tool_name,
                                "input_json": truncate(
                                    redact(_json.dumps(action_input, ensure_ascii=False))
                                ),
                                "output_json": truncate(redact(result)),
                                "success": 1 if success else 0,
                                "duration_ms": duration_ms,
                                "created_at": now,
                            },
                        )
                        return int(cursor.lastrowid or 0)
                except OperationalError as exc:
                    if _is_deadlock(exc) and attempt < 2:
                        last_exc = exc
                        time.sleep(0.05 * (attempt + 1) + random.random() * 0.05)
                        continue
                    raise
        assert last_exc is not None
        raise last_exc

    def list_tool_logs(self, session_id: str, limit: int = 20) -> list[dict[str, object]]:
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tool_name, input_json, output_json, success, duration_ms, created_at "
                    "FROM tool_logs WHERE session_id = :session_id "
                    "ORDER BY id DESC LIMIT :limit"
                ),
                {"session_id": session_id, "limit": limit},
            ).mappings()
        return [dict(row) for row in rows]

    def prune_before(self, days: int) -> dict[str, int]:
        """删除 N 天前的消息与工具日志（保留会话壳）。时间列是 ISO 字符串，按字符串比较。"""
        if days < 0:
            raise ValueError("days 不能为负数")
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        try:
            from sqlalchemy import text
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        counts: dict[str, int] = {}
        with self.engine.begin() as conn:
            counts["messages"] = int(
                conn.execute(
                    text("DELETE FROM messages WHERE created_at < :cutoff"),
                    {"cutoff": cutoff},
                ).rowcount
                or 0
            )
            counts["tool_logs"] = int(
                conn.execute(
                    text("DELETE FROM tool_logs WHERE created_at < :cutoff"),
                    {"cutoff": cutoff},
                ).rowcount
                or 0
            )
        return counts

"""MySQL Runtime 主存储（ADR-001）。

使用 SQLAlchemy 2.x Core + PyMySQL，通过连接池与显式事务边界访问 MySQL。
依赖未安装或连接失败时抛出明确错误；CLI/工厂负责给出降级提示。
"""

from __future__ import annotations

import random
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from agentkernel.memory.base import RuntimeStore
from agentkernel.utils.errors import AgentKernelError
from agentkernel.utils.observability import redact, truncate

# ADR-002：跨进程写同一会话靠 sessions 行锁串行化；进程内锁只是优化（且有界）
MAX_WRITE_ATTEMPTS = 3
MAX_SESSION_LOCKS = 1024


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
        self._session_locks: OrderedDict[str, threading.Lock] = OrderedDict()
        self._session_locks_guard = threading.Lock()

    def _session_lock(self, session_id: str) -> threading.Lock:
        """进程内锁（有界 LRU）：仅减少同进程竞争，跨进程正确性由 DB 行锁保证。"""
        with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is not None:
                self._session_locks.move_to_end(session_id)
                return lock
            lock = threading.Lock()
            self._session_locks[session_id] = lock
            if len(self._session_locks) > MAX_SESSION_LOCKS:
                self._session_locks.popitem(last=False)
            return lock

    @staticmethod
    def _backoff(attempt: int) -> None:
        """指数退避 + 抖动：0.05s → 0.1s（+ 0–50ms）。"""
        time.sleep(0.05 * (2**attempt) + random.random() * 0.05)

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

    def ensure_schema(self) -> None:
        """校验 schema 已由 Alembic 管理（G-16：不再自动建表）。"""
        try:
            from sqlalchemy import inspect
        except ImportError as exc:
            raise MySQLStoreError(
                "MySQL 主存储需要 SQLAlchemy/PyMySQL：pip install -e '.[mysql]'"
            ) from exc

        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        required = {"sessions", "messages", "tool_logs"}
        if "alembic_version" not in tables or not required <= tables:
            raise MySQLStoreError(
                "MySQL schema 未初始化：请先执行 "
                "`python -m agentkernel --migrate`（等价于 `alembic upgrade head`）"
            )
        columns = {column["name"] for column in inspector.get_columns("tool_logs")}
        if "duration_ms" not in columns:
            raise MySQLStoreError(
                "MySQL schema 过期（tool_logs 缺 duration_ms）：请执行 `python -m agentkernel --migrate`"
            )

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
        try:
            from sqlalchemy import text
            from sqlalchemy.exc import OperationalError
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        last_exc: Exception | None = None
        with self._session_lock(session_id):
            for attempt in range(MAX_WRITE_ATTEMPTS):
                try:
                    with self.engine.begin() as conn:
                        # ADR-002：先锁会话行，跨进程写同一会话在此串行化
                        locked = conn.execute(
                            text("SELECT id FROM sessions WHERE id = :id FOR UPDATE"),
                            {"id": session_id},
                        ).scalar()
                        if locked is None:
                            raise MySQLStoreError(f"会话不存在：{session_id}（先 create_session）")
                        # 取锁后再取时间：保证 updated_at 不早于本条消息
                        now = _now()
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
                    if _is_deadlock(exc) and attempt < MAX_WRITE_ATTEMPTS - 1:
                        last_exc = exc
                        self._backoff(attempt)
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

        try:
            from sqlalchemy import text
            from sqlalchemy.exc import OperationalError
        except ImportError as exc:
            raise MySQLStoreError("MySQL 主存储需要 SQLAlchemy：pip install -e '.[mysql]'") from exc

        last_exc: Exception | None = None
        with self._session_lock(session_id):
            for attempt in range(MAX_WRITE_ATTEMPTS):
                try:
                    with self.engine.begin() as conn:
                        # ADR-002：与消息写共用同一把会话行锁，保证同会话写顺序一致
                        locked = conn.execute(
                            text("SELECT id FROM sessions WHERE id = :id FOR UPDATE"),
                            {"id": session_id},
                        ).scalar()
                        if locked is None:
                            raise MySQLStoreError(f"会话不存在：{session_id}（先 create_session）")
                        now = _now()
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
                    if _is_deadlock(exc) and attempt < MAX_WRITE_ATTEMPTS - 1:
                        last_exc = exc
                        self._backoff(attempt)
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

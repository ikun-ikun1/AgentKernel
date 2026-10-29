"""SQLite 对话记忆：会话 + 消息持久化，重启不丢（借鉴 workbench 的 data/db_helper.py）。

设计要点（个人项目特点：零外部依赖，标准库 sqlite3 实现）：
- 每个会话一条记录，消息按追加顺序存储，带 created_at 时间戳。
- 默认库文件在 ~/.agentkernel/agentkernel.db；测试可传 :memory:。
- 单连接 + 锁，CLI 场景够用；打开 `WAL` 降低读写互锁概率。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);

-- 工具调用审计（对应 agent-study Ch14 的 tool_logs 表）
CREATE TABLE IF NOT EXISTS tool_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tool_logs_session_id ON tool_logs(session_id, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStore:
    """极简 SQLite 会话/消息存储。

    `append_message` 会顺便更新 `sessions.updated_at`，因此「最近会话」列表按活跃度排序。
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 会话 ----

    def create_session(self, session_id: str, title: str = "") -> str:
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, title or session_id, now, now),
            )
            self._conn.commit()
        return session_id

    def list_sessions(self, limit: int = 20) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, created_at, updated_at FROM sessions "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_session(self, session_id: str, title: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now(), session_id),
            )
            self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    # ---- 消息 ----

    def append_message(self, session_id: str, role: str, content: str) -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            self._conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def get_messages(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, str]]:
        sql = (
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY id ASC LIMIT ? OFFSET ?"
        )
        with self._lock:
            rows = self._conn.execute(
                sql, (session_id, -1 if limit is None else limit, offset)
            ).fetchall()
        return [dict(row) for row in rows]

    def count_messages(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    # ---- 工具调用审计 ----

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        action_input: dict[str, object],
        result: str,
        success: bool,
    ) -> int:
        import json as _json

        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO tool_logs "
                "(session_id, tool_name, input_json, output_json, success, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    tool_name,
                    _json.dumps(action_input, ensure_ascii=False),
                    result,
                    1 if success else 0,
                    now,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def list_tool_logs(self, session_id: str, limit: int = 20) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tool_name, input_json, output_json, success, created_at "
                "FROM tool_logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]


def default_store() -> SQLiteStore:
    """按环境变量 `AGENTKERNEL_DB_PATH` 创建默认存储。"""
    import os

    db_path = os.environ.get("AGENTKERNEL_DB_PATH") or "~/.agentkernel/agentkernel.db"
    return SQLiteStore(Path(db_path).expanduser())

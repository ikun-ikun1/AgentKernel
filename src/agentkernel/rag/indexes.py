"""持久化词法索引与可选 Chroma 向量索引（A4）。"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from agentkernel.rag.chunking import ShingleIndex
from agentkernel.rag.models import Chunk, SearchResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    doc_name TEXT NOT NULL,
    source TEXT NOT NULL,
    checksum TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_at REAL NOT NULL,
    ingested_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_name ON documents(doc_name);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL,
    page INTEGER,
    section TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(doc_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    tokenize='unicode61'
);
"""


class SQLiteIndex:
    """Durable document/chunk catalog with an FTS5 lexical index."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_document(self, doc_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()

    def upsert_document(self, document: dict[str, Any], chunks: list[Chunk]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM chunks_fts WHERE chunk_id IN "
                "(SELECT chunk_id FROM chunks WHERE doc_id = ?)",
                (document["doc_id"],),
            )
            self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (document["doc_id"],))
            self._conn.execute(
                "INSERT INTO documents "
                "(doc_id, doc_name, source, checksum, size_bytes, modified_at, ingested_at, chunk_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(doc_id) DO UPDATE SET doc_name=excluded.doc_name, "
                "source=excluded.source, checksum=excluded.checksum, size_bytes=excluded.size_bytes, "
                "modified_at=excluded.modified_at, ingested_at=excluded.ingested_at, "
                "chunk_count=excluded.chunk_count",
                (
                    document["doc_id"],
                    document["doc_name"],
                    document["source"],
                    document["checksum"],
                    document["size_bytes"],
                    document["modified_at"],
                    document["ingested_at"],
                    len(chunks),
                ),
            )
            for chunk in chunks:
                self._conn.execute(
                    "INSERT INTO chunks "
                    "(chunk_id, doc_id, ordinal, text, page, section, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        document["doc_id"],
                        int(chunk.metadata.get("ordinal", 0)),
                        chunk.text,
                        chunk.page,
                        chunk.section,
                        json.dumps(chunk.metadata, ensure_ascii=False),
                    ),
                )
                self._conn.execute(
                    "INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
                    (chunk.chunk_id, chunk.text),
                )

    def delete_document(self, doc_id: str) -> bool:
        with self._lock, self._conn:
            row = self.get_document(doc_id)
            if row is None:
                return False
            self._conn.execute(
                "DELETE FROM chunks_fts WHERE chunk_id IN "
                "(SELECT chunk_id FROM chunks WHERE doc_id = ?)",
                (doc_id,),
            )
            self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            return True

    def lexical_query(self, query: str, limit: int) -> list[SearchResult]:
        terms = [term for term in re.findall(r"[\w]+", query, flags=re.UNICODE) if term]
        if not terms:
            return []
        # Quote terms so user punctuation cannot become an FTS expression.
        fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT c.chunk_id, d.doc_name, c.text, c.page, c.section, d.source, "
                    "bm25(chunks_fts) AS rank "
                    "FROM chunks_fts JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id "
                    "JOIN documents d ON d.doc_id = c.doc_id "
                    "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        return [
            SearchResult(
                row["chunk_id"],
                row["doc_name"],
                row["text"],
                1.0 / (1.0 + max(float(row["rank"]), 0.0)),
                row["source"],
                row["page"],
                row["section"],
            )
            for row in rows
        ]

    def shingle_query(self, query: str, limit: int) -> list[SearchResult]:
        """Fallback for CJK text when SQLite's tokenizer yields no FTS terms."""
        index = ShingleIndex()
        index.add(self.all_chunks())
        return index.query(query, top_k=limit)

    def all_chunks(self, limit: int = 10000) -> list[Chunk]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*, d.doc_name, d.source FROM chunks c "
                "JOIN documents d ON d.doc_id = c.doc_id ORDER BY c.doc_id, c.ordinal LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Chunk(
                row["chunk_id"],
                row["doc_name"],
                row["text"],
                json.loads(row["metadata_json"]),
                row["source"],
                row["page"],
                row["section"],
            )
            for row in rows
        ]

    def list_documents(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT doc_name FROM documents ORDER BY doc_name").fetchall()
        return [str(row["doc_name"]) for row in rows]

    def find_document_id_by_name(self, doc_name: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_id FROM documents WHERE doc_name = ? ORDER BY ingested_at DESC LIMIT 1",
                (doc_name,),
            ).fetchone()
        return str(row["doc_id"]) if row else None

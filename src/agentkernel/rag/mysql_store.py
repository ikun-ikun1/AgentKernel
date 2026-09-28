"""MySQL 知识库存储（ADR-001）。

文档与 Chunk 事实数据存 MySQL，中文词法检索使用 InnoDB FULLTEXT + ngram parser。
向量索引仅作为可选增强，缺失时回退到本模块的 MySQL 词法检索。
"""
from __future__ import annotations

import json
import random
import time
from typing import Any

from agentkernel.rag.ingest import Chunk, SearchResult
from agentkernel.utils.errors import AgentKernelError


class MySQLKnowledgeError(AgentKernelError):
    """MySQL 知识库存储错误。"""


def _is_deadlock(exc: Exception) -> bool:
    """MySQL 1213 死锁 / 1205 锁等待超时：生产写入应重试。"""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", (None,)) if orig is not None else (None,)
    return bool(args) and args[0] in (1213, 1205)


class MySQLKnowledgeStore:
    """MySQL 8 文档目录 / Chunk / ngram 全文检索。"""

    def __init__(self, dsn: str) -> None:
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.exc import SQLAlchemyError
        except ImportError as exc:
            raise MySQLKnowledgeError(
                "MySQL 知识库需要 SQLAlchemy/PyMySQL：pip install -e '.[mysql]'"
            ) from exc

        self.dsn = dsn
        self._create_engine = create_engine
        self._sqlalchemy_error = SQLAlchemyError
        self._engine: Any = None

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = self._create_engine(
                self.dsn, pool_pre_ping=True, pool_recycle=3600, future=True
            )
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def ensure_tables(self) -> None:
        """创建文档/Chunk 表与 ngram 全文索引（Alembic 之外保留 dev 兜底）。"""
        try:
            from sqlalchemy import (
                Column,
                Float,
                Index,
                Integer,
                MetaData,
                String,
                Table,
                Text,
                text,
            )
        except ImportError as exc:
            raise MySQLKnowledgeError(
                "MySQL 知识库需要 SQLAlchemy/PyMySQL：pip install -e '.[mysql]'"
            ) from exc

        metadata = MetaData()
        documents = Table(
            "documents",
            metadata,
            Column("doc_id", String(64), primary_key=True),
            Column("doc_name", String(255), nullable=False),
            Column("source", String(1024), nullable=False),
            Column("checksum", String(64), nullable=False),
            Column("size_bytes", Integer, nullable=False),
            Column("modified_at", Float, nullable=False),
            Column("ingested_at", String(64), nullable=False),
            Column("chunk_count", Integer, nullable=False, server_default="0"),
        )
        chunks = Table(
            "chunks",
            metadata,
            Column("chunk_id", String(128), primary_key=True),
            Column("doc_id", String(64), nullable=False),
            Column("ordinal", Integer, nullable=False),
            Column("text", Text, nullable=False),
            Column("page", Integer),
            Column("section", String(512), nullable=False, server_default=""),
            # MySQL 8 does not allow defaults on TEXT columns; callers always
            # provide the serialized metadata explicitly.
            Column("metadata_json", Text, nullable=False),
        )
        Index("idx_documents_name", documents.c.doc_name)
        Index("idx_chunks_doc", chunks.c.doc_id, chunks.c.ordinal)
        # MySQL 的 ngram 全文索引需要显式 FULLTEXT DDL；SQLAlchemy 的普通
        # Index 编译器会生成不带 FULLTEXT 的 CREATE INDEX，无法附加 parser。
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.statistics "
                    "WHERE table_schema = DATABASE() AND table_name = 'chunks' "
                    "AND index_name = 'idx_chunks_ft' LIMIT 1"
                )
            ).first()
            if not exists:
                conn.execute(
                    text(
                        "CREATE FULLTEXT INDEX idx_chunks_ft ON chunks (text) "
                        "WITH PARSER ngram"
                    )
                )

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM documents WHERE doc_id = :doc_id"), {"doc_id": doc_id}
            ).mappings().first()
        return dict(row) if row else None

    def upsert_document(self, document: dict[str, Any], chunks: list[Chunk]) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError

        doc_id = document["doc_id"]
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        text("DELETE FROM chunks WHERE doc_id = :doc_id"), {"doc_id": doc_id}
                    )
                    conn.execute(
                        text(
                            "INSERT INTO documents "
                            "(doc_id, doc_name, source, checksum, size_bytes, modified_at, ingested_at, chunk_count) "
                            "VALUES (:doc_id, :doc_name, :source, :checksum, :size_bytes, :modified_at, "
                            ":ingested_at, :chunk_count) "
                            "ON DUPLICATE KEY UPDATE doc_name=VALUES(doc_name), source=VALUES(source), "
                            "checksum=VALUES(checksum), size_bytes=VALUES(size_bytes), "
                            "modified_at=VALUES(modified_at), ingested_at=VALUES(ingested_at), "
                            "chunk_count=VALUES(chunk_count)"
                        ),
                        {
                            "doc_id": doc_id,
                            "doc_name": document["doc_name"],
                            "source": document["source"],
                            "checksum": document["checksum"],
                            "size_bytes": document["size_bytes"],
                            "modified_at": document["modified_at"],
                            "ingested_at": document["ingested_at"],
                            "chunk_count": len(chunks),
                        },
                    )
                    for chunk in chunks:
                        conn.execute(
                            text(
                                "INSERT INTO chunks "
                                "(chunk_id, doc_id, ordinal, text, page, section, metadata_json) "
                                "VALUES (:chunk_id, :doc_id, :ordinal, :text, :page, :section, :metadata_json)"
                            ),
                            {
                                "chunk_id": chunk.chunk_id,
                                "doc_id": doc_id,
                                "ordinal": int(chunk.metadata.get("ordinal", 0)),
                                "text": chunk.text,
                                "page": chunk.page,
                                "section": chunk.section,
                                "metadata_json": json.dumps(chunk.metadata, ensure_ascii=False),
                            },
                        )
                    return
            except OperationalError as exc:
                if _is_deadlock(exc) and attempt < 2:
                    last_exc = exc
                    time.sleep(0.05 * (attempt + 1) + random.random() * 0.05)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    def delete_document(self, doc_id: str) -> bool:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM documents WHERE doc_id = :doc_id"), {"doc_id": doc_id}
            ).first()
            if not exists:
                return False
            conn.execute(text("DELETE FROM chunks WHERE doc_id = :doc_id"), {"doc_id": doc_id})
            conn.execute(text("DELETE FROM documents WHERE doc_id = :doc_id"), {"doc_id": doc_id})
            return True

    def lexical_query(self, query: str, limit: int) -> list[SearchResult]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.chunk_id, d.doc_name, c.text, c.page, c.section, d.source, "
                    "MATCH(c.text) AGAINST (:q IN NATURAL LANGUAGE MODE) AS score "
                    "FROM chunks c JOIN documents d ON d.doc_id = c.doc_id "
                    "WHERE MATCH(c.text) AGAINST (:q IN NATURAL LANGUAGE MODE) "
                    "ORDER BY score DESC LIMIT :limit"
                ),
                {"q": query, "limit": limit},
            ).mappings()
        return [
            SearchResult(
                chunk_id=row["chunk_id"],
                doc_name=row["doc_name"],
                text=row["text"],
                score=float(row["score"] or 0.0),
                source=row["source"],
                page=row["page"],
                section=row["section"],
            )
            for row in rows
        ]

    def shingle_query(self, query: str, limit: int) -> list[SearchResult]:
        from agentkernel.rag.ingest import ShingleIndex

        index = ShingleIndex()
        index.add(self.all_chunks())
        return index.query(query, top_k=limit)

    def all_chunks(self, limit: int = 10000) -> list[Chunk]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.*, d.doc_name, d.source FROM chunks c "
                    "JOIN documents d ON d.doc_id = c.doc_id "
                    "ORDER BY c.doc_id, c.ordinal LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings()
        return [
            Chunk(
                chunk_id=row["chunk_id"],
                doc_name=row["doc_name"],
                text=row["text"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                source=row["source"],
                page=row["page"],
                section=row["section"],
            )
            for row in rows
        ]

    def list_documents(self) -> list[str]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT doc_name FROM documents ORDER BY doc_name")).mappings()
        return [str(row["doc_name"]) for row in rows]

    def find_document_id_by_name(self, doc_name: str) -> str | None:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT doc_id FROM documents WHERE doc_name = :doc_name "
                    "ORDER BY ingested_at DESC LIMIT 1"
                ),
                {"doc_name": doc_name},
            ).mappings().first()
        return str(row["doc_id"]) if row else None

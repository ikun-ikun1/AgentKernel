"""Persistent document ingestion and hybrid retrieval.

The knowledge base is deliberately an infrastructure component, not a chat
feature. It keeps document fingerprints and chunks in SQLite, supports
incremental re-indexing, preserves page/source metadata, and can optionally
add a persistent Chroma + sentence-transformers vector index. SQLite FTS5 is
always the durable lexical baseline; missing vector dependencies never erase
the corpus or change its identifiers.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from agentkernel.utils.errors import AgentKernelError


class RAGError(AgentKernelError):
    """Document ingestion or retrieval error."""


SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".pdf"})


@dataclass(frozen=True)
class DocumentPart:
    text: str
    page: int | None = None
    section: str = ""


@dataclass
class Chunk:
    chunk_id: str
    doc_name: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    page: int | None = None
    section: str = ""


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    doc_name: str
    text: str
    score: float
    source: str = ""
    page: int | None = None
    section: str = ""

    def to_citation(self) -> str:
        location = self.doc_name
        if self.page is not None:
            location += f", 第 {self.page} 页"
        return f"[来源：{location}] {self.text}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_document_parts(path: str | Path) -> list[DocumentPart]:
    """Load a supported document while retaining PDF page boundaries."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise RAGError(f"文档不存在或不是文件：{file}")
    suffix = file.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return [DocumentPart(file.read_text(encoding="utf-8", errors="replace"))]
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore[import-not-found,import-untyped]
        except ImportError as exc:
            raise RAGError("解析 PDF 需要 PyMuPDF：pip install pymupdf") from exc
        try:
            with fitz.open(file) as document:
                return [
                    DocumentPart(page.get_text("text"), page=index + 1)
                    for index, page in enumerate(document)
                ]
        except Exception as exc:
            raise RAGError(f"PDF 解析失败：{file}: {exc}") from exc
    raise RAGError(f"暂不支持的文档类型：{suffix}（支持 PDF / MD / TXT）")


def load_document(path: str | Path) -> str:
    """Compatibility helper returning a document's text without metadata."""
    return "\n\n".join(part.text for part in load_document_parts(path))


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """Split paragraphs with overlap while guaranteeing bounded chunk size."""
    text = text.strip()
    if not text:
        return []
    if chunk_size <= overlap or overlap < 0:
        raise ValueError("chunk_size 必须大于 overlap，overlap 不能为负数")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            chunks.append(buffer)
            buffer = ""
        step = chunk_size - overlap
        for start in range(0, len(paragraph), step):
            piece = paragraph[start : start + chunk_size]
            if piece.strip():
                chunks.append(piece)
    if buffer:
        chunks.append(buffer)
    return chunks


def _shingles(text: str, n: int = 2) -> set[str]:
    normalized = "".join(text.lower().split())
    if not normalized:
        return set()
    return {
        normalized[index : index + n]
        for index in range(max(0, len(normalized) - n + 1))
    } or {normalized}


class ShingleIndex:
    """In-memory lexical index retained for fast unit-level use."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._shingle_sets: list[set[str]] = []
        self._docs: set[str] = set()

    def add(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            self._chunks.append(chunk)
            self._shingle_sets.append(_shingles(chunk.text))
            self._docs.add(chunk.doc_name)

    def query(self, text: str, top_k: int = 3) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k 必须 >= 1")
        query_shingles = _shingles(text)
        if not query_shingles:
            return []
        scored: list[SearchResult] = []
        for chunk, shingles in zip(self._chunks, self._shingle_sets):
            if not shingles:
                continue
            overlap = len(query_shingles & shingles)
            if overlap == 0:
                continue
            score = overlap / ((len(query_shingles) * len(shingles)) ** 0.5)
            scored.append(
                SearchResult(
                    chunk.chunk_id,
                    chunk.doc_name,
                    chunk.text,
                    score,
                    chunk.source,
                    chunk.page,
                    chunk.metadata.get("section", chunk.section),
                )
            )
        scored.sort(key=lambda result: (-result.score, result.chunk_id))
        return scored[:top_k]

    def list_documents(self) -> list[str]:
        return sorted(self._docs)


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
            rows = self._conn.execute(
                "SELECT doc_name FROM documents ORDER BY doc_name"
            ).fetchall()
        return [str(row["doc_name"]) for row in rows]

    def find_document_id_by_name(self, doc_name: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc_id FROM documents WHERE doc_name = ? ORDER BY ingested_at DESC LIMIT 1",
                (doc_name,),
            ).fetchone()
        return str(row["doc_id"]) if row else None


class _VectorIndex:
    """Optional persistent semantic index; SQLite remains the source of truth."""

    def __init__(self, persist_dir: Path, model_name: str) -> None:
        try:
            import chromadb  # type: ignore[import-not-found]
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RAGError(
                "语义检索需要 chromadb、sentence-transformers 和模型依赖；"
                "可先使用 lexical 后端，或安装 `pip install agentkernel[rag]`"
            ) from exc
        try:
            self._model = SentenceTransformer(model_name)
            self._client = chromadb.PersistentClient(path=str(persist_dir))
            self._collection = self._client.get_or_create_collection(
                name="knowledge_chunks", metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:
            raise RAGError(f"向量后端初始化失败：{type(exc).__name__}: {exc}") from exc

    def replace_document(self, doc_id: str, chunks: list[Chunk]) -> None:
        old = self._collection.get(where={"doc_id": doc_id}).get("ids") or []
        if old:
            self._collection.delete(ids=old)
        if not chunks:
            return
        embeddings = self._model.encode([chunk.text for chunk in chunks]).tolist()
        self._collection.add(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {
                    "doc_id": doc_id,
                    "doc_name": chunk.doc_name,
                    "source": chunk.source,
                    "page": chunk.page or -1,
                    "section": chunk.section,
                }
                for chunk in chunks
            ],
            embeddings=embeddings,
        )

    def query(self, text: str, limit: int) -> list[tuple[str, float]]:
        embedding = self._model.encode(text).tolist()
        result = self._collection.query(query_embeddings=[embedding], n_results=limit)
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [(str(chunk_id), 1.0 - float(distance)) for chunk_id, distance in zip(ids, distances)]


class KnowledgeBase:
    """Persistent corpus with lexical search and optional semantic hybrid search."""

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        backend: str = "lexical",
        embedding_model: str = "BAAI/bge-small-zh-v1.5",
        dsn: str | None = None,
        vector_dir: str | Path | None = None,
    ) -> None:
        if backend not in {"auto", "lexical", "hybrid", "semantic"}:
            raise ValueError("backend 必须是 auto、lexical、hybrid 或 semantic")

        self.dsn = dsn
        self.persist_dir = None
        self._mysql_store: Any = None

        if dsn and (dsn.startswith("mysql://") or dsn.startswith("mysql+pymysql://")):
            from agentkernel.rag.mysql_store import MySQLKnowledgeStore

            self._mysql_store = MySQLKnowledgeStore(dsn)
            self._mysql_store.ensure_tables()
            self._index: Any = self._mysql_store
        else:
            # `:memory:` 显式表示不落盘；用于测试与 eval。
            if persist_dir is not None and str(persist_dir) == ":memory:":
                persist_dir = None
            self.persist_dir = Path(persist_dir).expanduser() if persist_dir else None
            db_path = self.persist_dir / "knowledge.db" if self.persist_dir else ":memory:"
            if self.persist_dir:
                self.persist_dir.mkdir(parents=True, exist_ok=True)
            self._index = SQLiteIndex(db_path)

        # Chroma 向量索引是可选增强：MySQL 持久化时放在独立本地目录，不进入 MySQL。
        if vector_dir is not None:
            self._vector_dir = Path(vector_dir).expanduser()
        elif self.persist_dir:
            self._vector_dir = self.persist_dir / "vectors"
        else:
            self._vector_dir = Path.home() / ".agentkernel" / "vectors"

        self._vector: _VectorIndex | None = None
        self.backend_name = "lexical"
        self.backend_warning: str | None = None

        if backend == "semantic" and self.persist_dir is None and self._mysql_store is None:
            self._index.close()
            raise ValueError("semantic 后端需要持久化目录或 MySQL DSN，以便保存向量索引")

        if backend in {"auto", "hybrid", "semantic"} and (
            self.persist_dir or self._mysql_store is not None
        ):
            try:
                self._vector_dir.mkdir(parents=True, exist_ok=True)
                self._vector = _VectorIndex(self._vector_dir, embedding_model)
                self.backend_name = "hybrid" if backend != "semantic" else "semantic"
            except RAGError as exc:
                if backend == "semantic":
                    self._index.close()
                    raise
                self.backend_warning = f"{exc}；已降级为 MySQL ngram / SQLite FTS5 持久化检索"

    def close(self) -> None:
        self._index.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _doc_id(path: Path) -> str:
        return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]

    def ingest_file(self, path: str | Path, chunk_size: int = 500, overlap: int = 80) -> int:
        file = Path(path).expanduser().resolve()
        checksum = _sha256_file(file)
        doc_id = self._doc_id(file)
        current = self._index.get_document(doc_id)
        if current is not None and current["checksum"] == checksum:
            return 0

        parts = load_document_parts(file)
        chunks: list[Chunk] = []
        ordinal = 0
        for part in parts:
            for piece in chunk_text(part.text, chunk_size=chunk_size, overlap=overlap):
                chunk_id = f"{doc_id}:{ordinal}"
                chunks.append(
                    Chunk(
                        chunk_id=chunk_id,
                        doc_name=file.name,
                        text=piece,
                        metadata={"ordinal": ordinal, "source": str(file)},
                        source=str(file),
                        page=part.page,
                        section=part.section,
                    )
                )
                ordinal += 1
        document = {
            "doc_id": doc_id,
            "doc_name": file.name,
            "source": str(file),
            "checksum": checksum,
            "size_bytes": file.stat().st_size,
            "modified_at": file.stat().st_mtime,
            "ingested_at": _now(),
        }
        self._index.upsert_document(document, chunks)
        if self._vector is not None:
            self._vector.replace_document(doc_id, chunks)
        return len(chunks)

    def ingest_text(
        self, doc_name: str, text: str, chunk_size: int = 500, overlap: int = 80
    ) -> int:
        """Insert deterministic test/demo text into the same durable schema."""
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc_id = hashlib.sha256(f"text:{doc_name}".encode()).hexdigest()[:24]
        current = self._index.get_document(doc_id)
        if current is not None and current["checksum"] == checksum:
            return 0
        chunks = [
            Chunk(
                f"{doc_id}:{ordinal}",
                doc_name,
                piece,
                {"ordinal": ordinal},
                doc_name,
            )
            for ordinal, piece in enumerate(chunk_text(text, chunk_size, overlap))
        ]
        self._index.upsert_document(
            {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "source": doc_name,
                "checksum": checksum,
                "size_bytes": len(text.encode("utf-8")),
                "modified_at": 0.0,
                "ingested_at": _now(),
            },
            chunks,
        )
        if self._vector is not None:
            self._vector.replace_document(doc_id, chunks)
        return len(chunks)

    def delete_document(self, path_or_name: str | Path) -> bool:
        path = Path(path_or_name).expanduser()
        doc_id = self._doc_id(path.resolve()) if path.exists() else None
        if doc_id is None:
            doc_id = self._index.find_document_id_by_name(str(path_or_name))
            if doc_id is None:
                return False
        deleted = self._index.delete_document(doc_id)
        if deleted and self._vector is not None:
            self._vector.replace_document(doc_id, [])
        return deleted

    def query(self, text: str, top_k: int = 3) -> list[SearchResult]:
        if top_k < 1:
            raise ValueError("top_k 必须 >= 1")
        if self._vector is None:
            lexical = self._index.lexical_query(text, max(top_k * 4, 12))
            if not lexical:
                lexical = self._index.shingle_query(text, max(top_k * 4, 12))
            return lexical[:top_k]

        vector_hits = self._vector.query(text, max(top_k * 4, 12))
        by_id = {chunk.chunk_id: chunk for chunk in self._index.all_chunks()}

        if self.backend_name == "semantic":
            # semantic 后端只使用向量候选，避免词法结果影响纯语义召回观察
            results: list[SearchResult] = []
            for chunk_id, score in vector_hits:
                chunk = by_id.get(chunk_id)
                if chunk is not None:
                    results.append(
                        SearchResult(
                            chunk.chunk_id,
                            chunk.doc_name,
                            chunk.text,
                            score,
                            chunk.source,
                            chunk.page,
                            chunk.section,
                        )
                    )
            return results[:top_k]

        # hybrid：RRF 融合词法与语义候选；FTS5 为空时退回 shingle 供 CJK 查询
        lexical = self._index.lexical_query(text, max(top_k * 4, 12))
        if not lexical:
            lexical = self._index.shingle_query(text, max(top_k * 4, 12))
        fused: dict[str, float] = {}
        for rank, result in enumerate(lexical, 1):
            fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1.0 / (60 + rank)
        for rank, (chunk_id, _score) in enumerate(vector_hits, 1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (60 + rank)
        results = []
        for chunk_id, score in sorted(fused.items(), key=lambda item: (-item[1], item[0])):
            chunk = by_id.get(chunk_id)
            if chunk is not None:
                results.append(
                    SearchResult(
                        chunk.chunk_id,
                        chunk.doc_name,
                        chunk.text,
                        score,
                        chunk.source,
                        chunk.page,
                        chunk.section,
                    )
                )
        return results[:top_k]

    def list_documents(self) -> list[str]:
        return self._index.list_documents()

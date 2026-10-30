"""知识库应用层（A4）：入库/删除/检索编排，复用 loaders/chunking/indexes。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Self

from agentkernel.adapters.knowledge.chroma_vector import _VectorIndex
from agentkernel.rag.chunking import chunk_text
from agentkernel.rag.indexes import SQLiteIndex
from agentkernel.rag.loaders import load_document_parts
from agentkernel.rag.models import Chunk, RAGError, SearchResult, _now, _sha256_file


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
            from agentkernel.adapters.knowledge.mysql_ngram import MySQLKnowledgeStore

            self._mysql_store = MySQLKnowledgeStore(dsn)
            self._mysql_store.ensure_schema()
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

"""Chroma 向量索引适配器（A4）：可选语义增强，SQLite/MySQL 仍是事实源。"""

from __future__ import annotations

from pathlib import Path

from agentkernel.rag.models import Chunk, RAGError


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
        return [
            (str(chunk_id), 1.0 - float(distance)) for chunk_id, distance in zip(ids, distances)
        ]

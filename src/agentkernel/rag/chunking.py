"""分块与内存词法索引（A4）。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from agentkernel.rag.models import Chunk, SearchResult


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
    return {normalized[index : index + n] for index in range(max(0, len(normalized) - n + 1))} or {
        normalized
    }


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

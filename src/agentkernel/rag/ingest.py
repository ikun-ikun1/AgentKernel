"""文档解析（PDF/MD/TXT）→ 分块（带重叠）→ 向量化 → 检索。

个人项目特点：
- 首选 ChromaDB + bge-small-zh（按 README 技术栈），但依赖不安装时自动降级到
  纯 Python 的「字符 2-gram 相似度索引」，保证知识库链路在任何环境都能演示。
- 检索结果始终带来源（文档名 + 片段），这是「问答带来源引用」的底线。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from agentkernel.utils.errors import AgentKernelError


class RAGError(AgentKernelError):
    """知识库解析 / 检索错误。"""


@dataclass
class Chunk:
    chunk_id: str
    doc_name: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    doc_name: str
    text: str
    score: float

    def to_citation(self) -> str:
        return f"[来源：{self.doc_name}] {self.text}"


def load_document(path: str | Path) -> str:
    """按扩展名加载文档内容；PDF 依赖 PyMuPDF（fitz），未安装时给明确提示。"""
    file = Path(path)
    if not file.exists():
        raise RAGError(f"文档不存在：{file}")
    suffix = file.suffix.lower()
    if suffix in (".txt", ".md", ".markdown"):
        return file.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as e:
            raise RAGError(
                "解析 PDF 需要 PyMuPDF：pip install pymupdf"
            ) from e
        doc = fitz.open(file)
        try:
            return "\n\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    raise RAGError(f"暂不支持的文档类型：{suffix}（支持 PDF / MD / TXT）")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """按段落分块，块间保留 overlap 字符重叠，避免信息被切碎。"""
    text = text.strip()
    if not text:
        return []
    if chunk_size <= overlap:
        raise ValueError("chunk_size 必须大于 overlap")

    # 先按空行切段，长段再按字符硬切
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf:
            candidate = f"{buf}\n\n{para}"
        else:
            candidate = para
        if len(candidate) <= chunk_size:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        start = 0
        while start < len(para):
            chunks.append(para[start : start + chunk_size])
            start += chunk_size - overlap
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def _shingles(text: str, n: int = 2) -> set[str]:
    """字符 n-gram 集合：中文场景简单有效，零依赖。"""
    text = text.strip().lower()
    return {text[i : i + n] for i in range(max(0, len(text) - n + 1))} if len(text) >= n else {text}


class ShingleIndex:
    """纯 Python 降级检索引擎：字符 2-gram 余弦相似度。"""

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
        q = _shingles(text)
        if not q:
            return []
        scored: list[SearchResult] = []
        for chunk, shingles in zip(self._chunks, self._shingle_sets):
            if not shingles:
                continue
            overlap = len(q & shingles)
            if overlap == 0:
                continue
            score = overlap / ((len(q) * len(shingles)) ** 0.5)
            scored.append(SearchResult(chunk.doc_name, chunk.text, score))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]

    def list_documents(self) -> list[str]:
        return sorted(self._docs)


class _ChromaBackend:
    """ChromaDB + bge-small-zh 向量后端；依赖不装就不启用。"""

    def __init__(self, persist_dir: str) -> None:
        try:
            import chromadb  # type: ignore[import-not-found]
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as e:
            raise RAGError(
                "ChromaDB 后端需要：pip install chromadb sentence-transformers"
            ) from e

        self._model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="knowledge_base",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, chunks: Iterable[Chunk]) -> None:
        chunk_list = list(chunks)
        if not chunk_list:
            return
        self._collection.add(
            ids=[c.chunk_id for c in chunk_list],
            documents=[c.text for c in chunk_list],
            metadatas=[{"doc_name": c.doc_name, **c.metadata} for c in chunk_list],
            embeddings=[self._model.encode(c.text).tolist() for c in chunk_list],
        )

    def query(self, text: str, top_k: int = 3) -> list[SearchResult]:
        emb = self._model.encode(text).tolist()
        res = self._collection.query(query_embeddings=[emb], n_results=top_k)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        results: list[SearchResult] = []
        for doc, meta, dist in zip(docs, metas, distances):
            if doc is None:
                continue
            doc_name = str((meta or {}).get("doc_name", "unknown"))
            score = 1.0 - float(dist)  # cosine distance → similarity
            results.append(SearchResult(doc_name, doc, score))
        return results

    def list_documents(self) -> list[str]:
        metadatas = self._collection.get(include=["metadatas"]).get("metadatas") or []
        return sorted({str(m.get("doc_name")) for m in metadatas if m})


class KnowledgeBase:
    """知识库门面：自动选择 ChromaDB 或纯 Python 降级后端。"""

    def __init__(self, persist_dir: str | Path | None = None, backend: str = "auto") -> None:
        self.persist_dir = str(Path(persist_dir).expanduser() if persist_dir else "")
        self.backend_name = backend
        self._backend: Any = None
        self._init_backend()

    def _init_backend(self) -> None:
        if self.backend_name in ("auto", "chroma") and self.persist_dir:
            try:
                self._backend = _ChromaBackend(self.persist_dir)
                self.backend_name = "chroma"
                return
            except RAGError:
                if self.backend_name == "chroma":
                    raise
        self._backend = ShingleIndex()
        self.backend_name = "shingle-fallback"

    def ingest_file(self, path: str | Path, chunk_size: int = 500, overlap: int = 80) -> int:
        doc_name = Path(path).name
        text = load_document(path)
        chunks = [
            Chunk(
                chunk_id=f"{doc_name}:{i}",
                doc_name=doc_name,
                text=piece,
                metadata={"source": str(path)},
            )
            for i, piece in enumerate(chunk_text(text, chunk_size=chunk_size, overlap=overlap))
        ]
        self._backend.add(chunks)
        return len(chunks)

    def ingest_text(self, doc_name: str, text: str, chunk_size: int = 500, overlap: int = 80) -> int:
        chunks = [
            Chunk(chunk_id=f"{doc_name}:{i}", doc_name=doc_name, text=piece)
            for i, piece in enumerate(chunk_text(text, chunk_size=chunk_size, overlap=overlap))
        ]
        self._backend.add(chunks)
        return len(chunks)

    def query(self, text: str, top_k: int = 3) -> list[SearchResult]:
        return self._backend.query(text, top_k=top_k)

    def list_documents(self) -> list[str]:
        return self._backend.list_documents()

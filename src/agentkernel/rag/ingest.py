"""兼容 shim：RAG 已拆分到 models/loaders/chunking/indexes/knowledge（A4）。

保留旧 import 路径一个版本；内部代码请使用新模块。
"""

from __future__ import annotations

from agentkernel.rag.chunking import ShingleIndex, chunk_text
from agentkernel.rag.indexes import SQLiteIndex
from agentkernel.rag.knowledge import KnowledgeBase
from agentkernel.rag.loaders import load_document, load_document_parts
from agentkernel.rag.models import (
    SUPPORTED_SUFFIXES,
    Chunk,
    DocumentPart,
    RAGError,
    SearchResult,
)

__all__ = [
    "SUPPORTED_SUFFIXES",
    "Chunk",
    "DocumentPart",
    "KnowledgeBase",
    "RAGError",
    "SQLiteIndex",
    "SearchResult",
    "ShingleIndex",
    "chunk_text",
    "load_document",
    "load_document_parts",
]

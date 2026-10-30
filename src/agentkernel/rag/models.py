"""RAG 领域模型（A4）：文档、Chunk、检索结果与共享错误。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

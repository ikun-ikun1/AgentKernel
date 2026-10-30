"""文档加载（A4）：TXT/MD/PDF -> DocumentPart。"""

from __future__ import annotations

from pathlib import Path

from agentkernel.rag.models import DocumentPart, RAGError


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

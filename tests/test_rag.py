"""Persistent RAG ingestion, retrieval, and citation tests."""
from __future__ import annotations

import pytest

from agentkernel.rag.ingest import (
    Chunk,
    KnowledgeBase,
    RAGError,
    ShingleIndex,
    chunk_text,
    load_document,
)


def test_chunk_text_overlap():
    chunks = chunk_text("段落一。" * 200, chunk_size=100, overlap=20)
    assert chunks
    assert all(len(c) <= 100 for c in chunks)
    # 相邻块之间有重叠
    joined = chunks[0][-10:]
    assert joined in chunks[1]


def test_chunk_text_short_text_single_chunk():
    assert chunk_text("短文本", chunk_size=100, overlap=10) == ["短文本"]


def test_shingle_index_query():
    idx = ShingleIndex()
    idx.add(
        [
            Chunk(
                chunk_id="a:0", doc_name="a.md", text="AgentKernel 是一个从零实现的 Agent 内核"
            ),
            Chunk(chunk_id="b:0", doc_name="b.md", text="今天天气不错"),
        ]
    )
    results = idx.query("什么是 Agent 内核")
    assert results
    assert results[0].doc_name == "a.md"


def test_knowledge_base_ingest_and_query(tmp_path):
    kb = KnowledgeBase()  # 进程内纯 Python 索引
    path = tmp_path / "notes.md"
    path.write_text("AgentKernel 是个人项目，从零实现 ReAct 主循环。\n\n" * 10, encoding="utf-8")
    n = kb.ingest_file(path, chunk_size=80, overlap=20)
    assert n > 0
    assert path.name in kb.list_documents()

    results = kb.query("ReAct 主循环", top_k=2)
    assert results
    assert "ReAct 主循环" in results[0].text
    assert "来源" in results[0].to_citation()


def test_knowledge_base_no_result():
    kb = KnowledgeBase()
    assert kb.query("一个完全不存在的问题") == []


def test_knowledge_base_memory_explicit():
    kb = KnowledgeBase(persist_dir=":memory:")
    assert kb.persist_dir is None
    assert kb.ingest_text("notes.md", "AgentKernel 是一个 Runtime 研究原型") == 1
    # 内容未变化：checksum 命中，不重建
    assert kb.ingest_text("notes.md", "AgentKernel 是一个 Runtime 研究原型") == 0


def test_semantic_backend_requires_persist_dir():
    with pytest.raises(ValueError):
        KnowledgeBase(backend="semantic")


def test_knowledge_base_persists_and_updates_incrementally(tmp_path):
    kb_dir = tmp_path / "knowledge"
    source = tmp_path / "notes.md"
    source.write_text("第一版内容：ReAct 主循环。", encoding="utf-8")

    with KnowledgeBase(persist_dir=kb_dir, backend="lexical") as kb:
        assert kb.ingest_file(source) == 1
        assert kb.ingest_file(source) == 0  # checksum hit: no rebuild
        assert kb.query("ReAct")[0].text == "第一版内容：ReAct 主循环。"

    source.write_text("第二版内容：MCP 协议。", encoding="utf-8")
    with KnowledgeBase(persist_dir=kb_dir, backend="lexical") as kb:
        assert kb.ingest_file(source) == 1
        assert kb.query("MCP")[0].text == "第二版内容：MCP 协议。"
        assert kb.delete_document(source)
        assert kb.list_documents() == []


def test_load_document_unsupported(tmp_path):
    path = tmp_path / "x.docx"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(RAGError):
        load_document(path)


def test_load_document_pdf_preserves_page_text(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "notes.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "PDF page content")
    document.save(path)
    document.close()
    assert "PDF page content" in load_document(path)


def test_load_document_txt_and_md(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("纯文本内容", encoding="utf-8")
    assert load_document(txt) == "纯文本内容"

    md = tmp_path / "b.md"
    md.write_text("# 标题\n正文内容", encoding="utf-8")
    assert load_document(md) == "# 标题\n正文内容"

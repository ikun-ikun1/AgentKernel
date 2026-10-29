"""initial MySQL schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-01

ADR-001: MySQL 8 作为主存储，包含 Runtime 状态表与知识库文档/Chunk 表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Runtime 状态 ----
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(64),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
    )
    op.create_table(
        "tool_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(64),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("input_json", sa.Text, nullable=False),
        sa.Column("output_json", sa.Text, nullable=False),
        sa.Column("success", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(64), nullable=False),
    )
    op.create_index("idx_messages_session_id", "messages", ["session_id"])
    op.create_index("idx_tool_logs_session_id", "tool_logs", ["session_id"])

    # ---- 知识库文档 / Chunk ----
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.String(64), primary_key=True),
        sa.Column("doc_name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(1024), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("modified_at", sa.Float, nullable=False),
        sa.Column("ingested_at", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(128), primary_key=True),
        sa.Column(
            "doc_id",
            sa.String(64),
            sa.ForeignKey("documents.doc_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("page", sa.Integer),
        sa.Column("section", sa.String(512), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.Text, nullable=False),
    )
    op.create_index("idx_documents_name", "documents", ["doc_name"])
    op.create_index("idx_chunks_doc", "chunks", ["doc_id", "ordinal"])
    # MySQL 8 中文词法基线：ngram 全文索引
    op.execute("CREATE FULLTEXT INDEX idx_chunks_ft ON chunks (text) WITH PARSER ngram")


def downgrade() -> None:
    # 先删子表（chunks 引用 documents，且 chunks 上的 FULLTEXT/普通索引随表一起删）；
    # 不要在删表前单独 DROP INDEX —— MySQL 会报 1553（索引被外键依赖）。
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("tool_logs")
    op.drop_table("messages")
    op.drop_table("sessions")

"""tool_logs.duration_ms（expand-only，P1/G-11）

Revision ID: 0002_tool_log_duration
Revises: 0001_initial
Create Date: 2026-10-29

只加可空列：老代码继续可写（不传 duration_ms 即 NULL），不破坏回滚；
contract（改为 NOT NULL / 删除旧列）留到下一版。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_tool_log_duration"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_logs", sa.Column("duration_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_logs", "duration_ms")

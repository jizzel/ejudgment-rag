"""M3: ``llm_usage_ledger``, one row per generation request (usage and estimated cost).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09 10:05:12.402117
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("status IN ('ok', 'error')", name=op.f("ck_llm_usage_ledger_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usage_ledger")),
    )
    op.create_index("ix_llm_usage_ledger_created_at", "llm_usage_ledger", ["created_at"])
    op.create_index("ix_llm_usage_ledger_run_id", "llm_usage_ledger", ["run_id"])


def downgrade() -> None:
    op.drop_table("llm_usage_ledger")

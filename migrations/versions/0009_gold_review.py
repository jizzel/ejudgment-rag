"""Gold-set review: questions with labels and history; a `reviewer` role for lawyers.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-10 11:26:04.267456
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gold_questions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expect_no_answer", sa.Boolean(), nullable=False),
        sa.Column("gold_canonical_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gold_passages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('citation', 'case_name', 'issue', 'fact_pattern', 'out_of_corpus')",
            name=op.f("ck_gold_questions_category"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'retired')", name=op.f("ck_gold_questions_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_gold_questions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_gold_questions_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_gold_questions_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gold_questions")),
    )
    op.create_index("ix_gold_questions_status", "gold_questions", ["status"], unique=False)
    op.create_table(
        "gold_question_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('created', 'imported', 'edited', 'approved', 'reopened', 'retired')",
            name=op.f("ck_gold_question_history_action"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["gold_questions.id"],
            name=op.f("fk_gold_question_history_question_id_gold_questions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_gold_question_history_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gold_question_history")),
    )
    op.create_index(
        "ix_gold_question_history_question_id",
        "gold_question_history",
        ["question_id", "created_at"],
        unique=False,
    )

    # users.role gains "reviewer" (autogenerate does not compare CHECK constraints).
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_role"), "users", "role IN ('admin', 'researcher', 'reviewer')"
    )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'researcher' WHERE role = 'reviewer'")
    op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_role"), "users", "role IN ('admin', 'researcher')")
    op.drop_index("ix_gold_question_history_question_id", table_name="gold_question_history")
    op.drop_table("gold_question_history")
    op.drop_index("ix_gold_questions_status", table_name="gold_questions")
    op.drop_table("gold_questions")

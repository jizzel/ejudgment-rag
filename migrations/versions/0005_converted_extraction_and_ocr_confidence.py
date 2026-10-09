"""M2b: ``converted`` extraction method (Word files) and per-page OCR confidence.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09 02:48:17.709445
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Full name as created by migration 0001 (op.f stops the naming convention re-prefixing it).
CONSTRAINT = "ck_document_pages_extraction_method"


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    op.drop_constraint(op.f(CONSTRAINT), "document_pages", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        "document_pages",
        "extraction_method IN ('pdf_text', 'ocr', 'converted', 'legacy')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM document_pages WHERE extraction_method = 'converted'")
    op.drop_constraint(op.f(CONSTRAINT), "document_pages", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "document_pages", "extraction_method IN ('pdf_text', 'ocr', 'legacy')"
    )
    op.drop_column("document_pages", "ocr_confidence")

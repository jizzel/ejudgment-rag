"""Record which extractor produced each converted/OCR page, so extractor changes reprocess.

Pages extracted before this revision get the version of the code that produced them: Word
pages ``docx-v1``; OCR pages the engine name of the latest extract job that OCR'd documents
plus ``psm1-tsv-v1`` (the OCR settings and parser of revision 0005). Without such a job they
stay NULL and are extracted again. Importer pages (``pdf_text``, ``legacy``) stay NULL.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09 09:12:40.118204
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("extractor_version", sa.Text(), nullable=True))
    op.execute(
        "UPDATE document_pages SET extractor_version = 'docx-v1' "
        "WHERE extraction_method = 'converted'"
    )
    op.execute(
        """
        UPDATE document_pages SET extractor_version = job.source_version || '; psm1-tsv-v1'
        FROM (
            SELECT source_version FROM ingestion_jobs
            WHERE kind = 'extract' AND (counts->>'ocr_documents')::int > 0
            ORDER BY started_at DESC LIMIT 1
        ) AS job
        WHERE extraction_method = 'ocr'
        """
    )


def downgrade() -> None:
    op.drop_column("document_pages", "extractor_version")

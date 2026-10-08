"""Embed every chunk of eligible judgments with the configured provider.

Idempotent and resumable: the exact input text for each chunk (template ``ctx-v1``) is
rebuilt and hashed every run; only chunks whose stored ``embedding_input_hash`` is missing
or different are (re-)embedded. A metadata change that alters the input re-embeds the
affected chunks even when their content is unchanged.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Engine, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ejudgment.domain.enums import EligibilityStatus
from ejudgment.domain.models import Chunk, ChunkEmbedding, Judgment, ModelRegistry
from ejudgment.embeddings.base import EmbeddingProvider
from ejudgment.embeddings.template import TEMPLATE_VERSION, build_input
from ejudgment.ingestion.tokenizer import Tokenizer

logger = logging.getLogger(__name__)

CHUNKS = cast(Table, Chunk.__table__)
JUDGMENTS = cast(Table, Judgment.__table__)
EMBEDDINGS = cast(Table, ChunkEmbedding.__table__)
REGISTRY = cast(Table, ModelRegistry.__table__)


@dataclass
class EmbedReport:
    model_id: str
    model_revision: str
    template_version: str
    chunks_seen: int = 0
    embedded_new: int = 0
    re_embedded: int = 0
    skipped_unchanged: int = 0
    seconds: float = 0.0

    @property
    def per_second(self) -> float:
        done = self.embedded_new + self.re_embedded
        return round(done / self.seconds, 1) if self.seconds else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "seconds": round(self.seconds, 1), "per_second": self.per_second}


def register_model(conn: Connection, provider: EmbeddingProvider) -> None:
    conn.execute(
        pg_insert(REGISTRY)
        .values(
            model_id=provider.model_id,
            revision=provider.model_revision,
            kind="embedding",
            dimension=provider.dimension,
        )
        .on_conflict_do_nothing()
    )


def _existing_hashes(
    conn: Connection, chunk_ids: list[uuid.UUID], provider: EmbeddingProvider
) -> dict[uuid.UUID, str]:
    rows = conn.execute(
        select(EMBEDDINGS.c.chunk_id, EMBEDDINGS.c.embedding_input_hash).where(
            EMBEDDINGS.c.chunk_id.in_(chunk_ids),
            EMBEDDINGS.c.model_id == provider.model_id,
            EMBEDDINGS.c.model_revision == provider.model_revision,
        )
    )
    return {row.chunk_id: row.embedding_input_hash for row in rows}


def run_embedding(
    engine: Engine,
    provider: EmbeddingProvider,
    tokenizer: Tokenizer,
    *,
    limit: int | None = None,
    read_batch: int = 2000,
    embed_batch: int = 256,
) -> EmbedReport:
    report = EmbedReport(provider.model_id, provider.model_revision, TEMPLATE_VERSION)
    started = time.perf_counter()
    with engine.begin() as conn:
        register_model(conn, provider)

    query = (
        select(
            CHUNKS.c.id,
            CHUNKS.c.content,
            CHUNKS.c.content_hash,
            CHUNKS.c.section_label,
            JUDGMENTS.c.title,
            JUDGMENTS.c.court_name,
            JUDGMENTS.c.judgment_date,
        )
        .join(JUDGMENTS, JUDGMENTS.c.id == CHUNKS.c.judgment_id)
        .where(JUDGMENTS.c.eligibility_status == EligibilityStatus.ELIGIBLE.value)
        .order_by(CHUNKS.c.id)
    )
    if limit is not None:
        query = query.limit(limit)

    last_id: uuid.UUID | None = None
    while True:
        page = query.limit(min(read_batch, limit - report.chunks_seen) if limit else read_batch)
        if last_id is not None:
            page = page.where(CHUNKS.c.id > last_id)
        with engine.connect() as conn:
            rows = conn.execute(page).all()
            if not rows:
                break
            existing = _existing_hashes(conn, [row.id for row in rows], provider)
        last_id = rows[-1].id
        report.chunks_seen += len(rows)

        todo: list[tuple[Any, str, str]] = []
        for row in rows:
            built = build_input(
                row.content,
                title=row.title,
                court_name=row.court_name,
                judgment_date=row.judgment_date,
                section=row.section_label,
                tokenizer=tokenizer,
                max_tokens=provider.max_input_tokens,
            )
            previous = existing.get(row.id)
            if previous == built.input_hash:
                report.skipped_unchanged += 1
                continue
            todo.append((row, built.text, built.input_hash))
            if previous is None:
                report.embedded_new += 1
            else:
                report.re_embedded += 1

        for start in range(0, len(todo), embed_batch):
            batch = todo[start : start + embed_batch]
            vectors = provider.embed_documents([text for _, text, _ in batch])
            values = [
                {
                    "chunk_id": row.id,
                    "model_id": provider.model_id,
                    "model_revision": provider.model_revision,
                    "dimension": provider.dimension,
                    "embedding": vector,
                    "content_hash": row.content_hash,
                    "embedding_input_hash": input_hash,
                    "embedding_template_version": TEMPLATE_VERSION,
                }
                for (row, _, input_hash), vector in zip(batch, vectors, strict=True)
            ]
            statement = pg_insert(EMBEDDINGS).values(values)
            with engine.begin() as conn:
                conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=["chunk_id", "model_id", "model_revision"],
                        set_={
                            key: statement.excluded[key]
                            for key in (
                                "embedding",
                                "dimension",
                                "content_hash",
                                "embedding_input_hash",
                                "embedding_template_version",
                            )
                        },
                    )
                )
        logger.info(
            "Embedding: %d seen, %d new, %d re-embedded, %d unchanged",
            report.chunks_seen,
            report.embedded_new,
            report.re_embedded,
            report.skipped_unchanged,
        )
        if limit is not None and report.chunks_seen >= limit:
            break
    report.seconds = time.perf_counter() - started
    return report

"""Reciprocal Rank Fusion of the lexical and dense channels, and rerank ordering.

Pure functions over already-ranked candidate lists. Ordering is fully deterministic: ties
keep the earlier position (lexical before dense, then chunk id), so pages are stable.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from ejudgment.retrieval.repository import PassageRow


@dataclass
class Candidate:
    row: PassageRow
    lexical_score: float | None = None
    lexical_rank: int | None = None
    dense_score: float | None = None
    dense_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None

    @property
    def chunk_id(self) -> uuid.UUID:
        return self.row.chunk_id


def from_lexical(rows: Sequence[PassageRow]) -> list[Candidate]:
    return [
        Candidate(row, lexical_score=row.score, lexical_rank=rank)
        for rank, row in enumerate(rows, start=1)
    ]


def from_dense(rows: Sequence[tuple[PassageRow, float]]) -> list[Candidate]:
    return [
        Candidate(row, dense_score=similarity, dense_rank=rank)
        for rank, (row, similarity) in enumerate(rows, start=1)
    ]


def passage_identity(row: PassageRow) -> tuple[str, str]:
    """What makes two chunks "the same passage": identical text in the same source text.

    A judgment published under several URIs has one chunk per URI for each passage. The
    lexical channel keeps the copy from the first URI, while the dense channel keeps the
    most similar copy, and the copies' embeddings differ because each includes its own
    title/court/year context. Fusing by chunk id would split one passage in two.
    """
    return row.source_text_hash, row.content_hash


def rrf_fuse(
    lexical: Sequence[PassageRow], dense: Sequence[tuple[PassageRow, float]], k: int
) -> list[Candidate]:
    """score = sum over channels of 1 / (k + rank). Missing from a channel contributes 0.

    Candidates are merged by :func:`passage_identity`; the representative chunk (its URI
    and provenance) is the first copy seen, i.e. the lexical one when both channels found it.
    """
    merged: dict[tuple[str, str], Candidate] = {}
    first_seen: dict[tuple[str, str], int] = {}
    for candidate in [*from_lexical(lexical), *from_dense(dense)]:
        identity = passage_identity(candidate.row)
        existing = merged.get(identity)
        if existing is None:
            merged[identity] = candidate
            first_seen[identity] = len(first_seen)
            continue
        if candidate.dense_rank is not None and existing.dense_rank is None:
            existing.dense_rank = candidate.dense_rank
            existing.dense_score = candidate.dense_score
        if candidate.lexical_rank is not None and existing.lexical_rank is None:
            existing.lexical_rank = candidate.lexical_rank
            existing.lexical_score = candidate.lexical_score
    for candidate in merged.values():
        candidate.rrf_score = sum(
            1.0 / (k + rank)
            for rank in (candidate.lexical_rank, candidate.dense_rank)
            if rank is not None
        )
    return sorted(
        merged.values(),
        key=lambda c: (
            -(c.rrf_score or 0.0),
            first_seen[passage_identity(c.row)],
            str(c.chunk_id),
        ),
    )


def apply_rerank(candidates: list[Candidate], scores: Sequence[float]) -> list[Candidate]:
    """Reorder the first ``len(scores)`` candidates by rerank score; the rest keep order."""
    head = candidates[: len(scores)]
    for candidate, score in zip(head, scores, strict=True):
        candidate.rerank_score = score
    position = {id(candidate): index for index, candidate in enumerate(head)}
    head = sorted(head, key=lambda c: (-(c.rerank_score or 0.0), position[id(c)]))
    return [*head, *candidates[len(scores) :]]

"""How many eligible chunks have vectors for the loaded embedding model.

A model can load fine while its vectors are missing (fresh database, interrupted
``worker.embed``) or stale (built from judgment metadata that has since changed; those are
not counted). Search uses this to report
that state instead of claiming a dense or hybrid result. The count costs ~80 ms warm on the
real corpus, so it is cached briefly per database and model.
"""

import threading
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ejudgment.domain.enums import EligibilityStatus
from ejudgment.retrieval.repository import CONTEXT_HASH_SQL


@dataclass(frozen=True)
class Coverage:
    total: int
    embedded: int

    @property
    def missing(self) -> int:
        return self.total - self.embedded


_cache: dict[tuple[str, str, str], tuple[float, Coverage]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def embedding_coverage(
    conn: Connection, model_id: str, model_revision: str, ttl_seconds: float
) -> Coverage:
    database = conn.engine.url.render_as_string(hide_password=True)
    key = (database, model_id, model_revision)
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
    if cached is not None and now - cached[0] < ttl_seconds:
        return cached[1]
    row = conn.execute(
        text(
            "SELECT count(*) AS total, count(e.chunk_id) AS embedded "
            "FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            "LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id "
            "AND e.model_id = :model AND e.model_revision = :revision "
            # Only vectors built from the judgment's current metadata count as present.
            f"AND e.context_hash = {CONTEXT_HASH_SQL} "
            "WHERE j.eligibility_status = :eligible"
        ),
        {
            "model": model_id,
            "revision": model_revision,
            "eligible": EligibilityStatus.ELIGIBLE.value,
        },
    ).one()
    coverage = Coverage(total=int(row.total), embedded=int(row.embedded))
    with _lock:
        _cache[key] = (now, coverage)
    return coverage

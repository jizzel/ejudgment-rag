"""Evidence IDs: map the model's source labels back to retrieved passages, and re-check
that every passage still belongs to an eligible judgment with an eligible source."""

import uuid
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ejudgment.domain.enums import EligibilityStatus, RightsStatus
from ejudgment.generation.prompt import LabelledSource

ELIGIBLE_RIGHTS = (RightsStatus.CC_BY_NC_LOCAL_EXPORT.value, RightsStatus.LICENSED.value)


def eligible_chunk_ids(conn: Connection, chunk_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(chunk_ids)
    if not ids:
        return set()
    rows = conn.execute(
        text(
            "SELECT c.id FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            "JOIN document_sources s ON s.id = c.source_id "
            "WHERE c.id = ANY(:ids) AND j.eligibility_status = :eligible "
            "AND s.rights_status = ANY(:rights)"
        ),
        {"ids": ids, "eligible": EligibilityStatus.ELIGIBLE.value, "rights": list(ELIGIBLE_RIGHTS)},
    )
    return {row.id for row in rows}


def resolve_labels(
    labels: list[str], sources: dict[str, LabelledSource]
) -> tuple[list[LabelledSource], list[str]]:
    """Known sources (in citation order, without repeats) and the labels that match none."""
    found: list[LabelledSource] = []
    invalid: list[str] = []
    for raw in labels:
        label = raw.strip().strip("[]").upper()
        source = sources.get(label)
        if source is None:
            invalid.append(raw)
        elif source not in found:
            found.append(source)
    return found, invalid

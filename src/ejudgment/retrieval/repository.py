"""SQL for retrieval. Every query joins ``judgments`` and keeps only eligible records.

Filters are applied in SQL exactly as given (strict); values are always bound parameters.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ejudgment.domain.enums import EligibilityStatus
from ejudgment.domain.schemas import SearchFilters
from ejudgment.ingestion.normalize import NeutralCitation, normalize_citation
from ejudgment.retrieval.query import escape_like, party_patterns

# Minimum pg_trgm word similarity for a case-name match.
CASE_NAME_MIN_SIMILARITY = 0.6

_JUDGMENT_COLUMNS = (
    "j.id AS judgment_id, j.canonical_uri, j.citation, j.title, j.court_code, j.court_name, "
    "j.jurisdiction, j.judgment_date"
)


@dataclass(frozen=True)
class JudgmentRow:
    judgment_id: uuid.UUID
    canonical_uri: str
    citation: str
    title: str | None
    court_code: str | None
    court_name: str | None
    jurisdiction: str | None
    judgment_date: date | None


@dataclass(frozen=True)
class PassageRow:
    judgment: JudgmentRow
    chunk_id: uuid.UUID
    content: str
    content_hash: str
    source_text_hash: str
    section_label: str | None
    paragraph_refs: list[str]
    page_reference_status: str
    page_start: int | None
    page_end: int | None
    score: float


def _judgment(row: Any) -> JudgmentRow:
    return JudgmentRow(
        row.judgment_id,
        row.canonical_uri,
        row.citation,
        row.title,
        row.court_code,
        row.court_name,
        row.jurisdiction,
        row.judgment_date,
    )


def filter_sql(filters: SearchFilters, params: dict[str, Any]) -> str:
    """WHERE fragment over alias ``j`` (always restricted to eligible judgments)."""
    clauses = ["j.eligibility_status = :eligible"]
    params["eligible"] = EligibilityStatus.ELIGIBLE.value
    if filters.court is not None:
        clauses.append("j.court_code = :court")
        params["court"] = filters.court
    if filters.jurisdiction is not None:
        clauses.append("j.jurisdiction = :jurisdiction")
        params["jurisdiction"] = filters.jurisdiction
    if filters.year_from is not None:
        clauses.append("j.judgment_date >= make_date(:year_from, 1, 1)")
        params["year_from"] = filters.year_from
    if filters.year_to is not None:
        clauses.append("j.judgment_date < make_date(:year_to + 1, 1, 1)")
        params["year_to"] = filters.year_to
    if filters.judge is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements_text(j.judges) AS judge(name) "
            "WHERE judge.name ILIKE :judge ESCAPE '\\')"
        )
        params["judge"] = f"%{escape_like(filters.judge)}%"
    return " AND ".join(clauses)


def citation_matches(
    conn: Connection, citation: NeutralCitation, filters: SearchFilters
) -> list[JudgmentRow]:
    params: dict[str, Any] = {
        "neutral": str(citation).upper(),
        # citation_normalized drops brackets: "... 2020 GHASC 104 ..."; never match 1040.
        "pattern": rf"(^| ){citation.year} {citation.court.upper()} {citation.number}( |$)",
    }
    where = filter_sql(filters, params)
    rows = conn.execute(
        text(
            f"SELECT {_JUDGMENT_COLUMNS} FROM judgments j "
            f"WHERE (upper(j.neutral_citation) = :neutral OR j.citation_normalized ~ :pattern) "
            f"AND {where} ORDER BY j.judgment_date, j.canonical_uri"
        ),
        params,
    )
    return [_judgment(row) for row in rows]


def case_name_matches(
    conn: Connection, query: str, filters: SearchFilters, limit: int
) -> list[tuple[JudgmentRow, float]]:
    """Fuzzy case-name lookup. The party check runs in SQL, before the limit, so common
    party names ("Republic", "Tanzania") cannot push the real case out of the result."""
    params: dict[str, Any] = {
        "q": normalize_citation(query),
        "min_sim": CASE_NAME_MIN_SIMILARITY,
        "limit": limit,
    }
    where = filter_sql(filters, params)
    for index, pattern in enumerate(party_patterns(query)):
        where += f" AND j.citation_normalized ~ :party_{index}"
        params[f"party_{index}"] = pattern
    rows = conn.execute(
        text(
            f"SELECT {_JUDGMENT_COLUMNS}, word_similarity(:q, j.citation_normalized) AS sim "
            f"FROM judgments j WHERE :q <% j.citation_normalized AND {where} "
            f"AND word_similarity(:q, j.citation_normalized) >= :min_sim "
            f"ORDER BY sim DESC, j.canonical_uri LIMIT :limit"
        ),
        params,
    )
    return [(_judgment(row), float(row.sim)) for row in rows]


_PASSAGE_COLUMNS = (
    f"{_JUDGMENT_COLUMNS}, c.id AS chunk_id, c.content, c.content_hash, c.source_text_hash, "
    "c.section_label, c.paragraph_refs, c.page_reference_status, c.page_start, c.page_end"
)


def _passage(row: Any, score: float) -> PassageRow:
    return PassageRow(
        judgment=_judgment(row),
        chunk_id=row.chunk_id,
        content=row.content,
        content_hash=row.content_hash,
        source_text_hash=row.source_text_hash,
        section_label=row.section_label,
        paragraph_refs=[str(ref) for ref in row.paragraph_refs],
        page_reference_status=row.page_reference_status,
        page_start=row.page_start,
        page_end=row.page_end,
        score=score,
    )


def lexical_passages(
    conn: Connection, query: str, filters: SearchFilters, limit: int, per_case: int
) -> list[PassageRow]:
    """Chunks matching the query under either the stemmed or the exact-token config.

    Diversified in SQL, before the limit: at most ``per_case`` passages per case (whole
    source text), so one long judgment, or one judgment published under several URIs,
    cannot fill the candidate pool. Within a case an identical passage is kept once (the
    copy from the first URI); across different cases identical passages are all kept.
    """
    params: dict[str, Any] = {"q": query, "limit": limit, "per_case": per_case}
    where = filter_sql(filters, params)
    rows = conn.execute(
        text(
            "WITH q AS (SELECT websearch_to_tsquery('english', :q) AS en, "
            "websearch_to_tsquery('simple', :q) AS si), "
            "matches AS ("
            f"  SELECT DISTINCT ON (c.source_text_hash, c.content_hash) {_PASSAGE_COLUMNS}, "
            "  ts_rank_cd(c.textsearch_en, q.en) + ts_rank_cd(c.textsearch_simple, q.si) AS score "
            "  FROM chunks c JOIN judgments j ON j.id = c.judgment_id, q "
            "  WHERE (c.textsearch_en @@ q.en OR c.textsearch_simple @@ q.si) "
            f"  AND {where} "
            "  ORDER BY c.source_text_hash, c.content_hash, score DESC, j.canonical_uri, c.id"
            "), ranked AS ("
            "  SELECT m.*, row_number() OVER ("
            "    PARTITION BY m.source_text_hash ORDER BY m.score DESC, m.chunk_id"
            "  ) AS case_rank FROM matches m"
            ") "
            "SELECT * FROM ranked WHERE case_rank <= :per_case "
            "ORDER BY score DESC, chunk_id LIMIT :limit"
        ),
        params,
    )
    return [_passage(row, float(row.score)) for row in rows]


# SQL twin of ``embeddings.template.context_hash`` over alias ``j``: a vector takes part in
# dense search only while the judgment metadata it was built from is unchanged.
CONTEXT_HASH_SQL = (
    "md5(coalesce(j.title, '') || chr(31) || coalesce(j.court_name, '') || chr(31) || "
    "coalesce(extract(year FROM j.judgment_date)::int::text, ''))"
)

_SAFE_LITERAL = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")


def _literal(value: str) -> str:
    """Quote a configuration value (model id/revision) as an SQL literal.

    Inlined rather than bound so the planner can match the partial HNSW index predicate
    even when psycopg switches to prepared statements with generic plans.
    """
    if not _SAFE_LITERAL.match(value):
        raise ValueError(f"unsafe model identifier: {value!r}")
    return f"'{value}'"


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def dense_passages(
    conn: Connection,
    query_vector: list[float],
    *,
    model_id: str,
    model_revision: str,
    dimension: int,
    filters: SearchFilters,
    limit: int,
    per_case: int,
    ef_search: int,
    raw_neighbours: int,
) -> list[tuple[PassageRow, float]]:
    """Nearest chunks by cosine similarity, capped per case before the limit like the
    lexical channel. Returns ``(passage, similarity)`` in descending similarity."""
    if len(query_vector) != dimension:
        raise ValueError(f"query vector has {len(query_vector)} dims, expected {dimension}")
    dim = int(dimension)
    params: dict[str, Any] = {
        "q": vector_literal(query_vector),
        "limit": limit,
        "per_case": per_case,
        # Nearest neighbours fetched (after filtering) before per-case capping.
        "raw": max(raw_neighbours, limit),
    }
    where = filter_sql(filters, params)
    # Iterative scans keep fetching neighbours when strict filters reject many of them.
    conn.execute(
        text(
            "SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), "
            "set_config('hnsw.ef_search', :ef, true)"
        ),
        {"ef": str(ef_search)},
    )
    distance = f"(e.embedding::vector({dim})) <=> CAST(:q AS vector({dim}))"
    rows = conn.execute(
        text(
            "WITH nn AS ("
            f"  SELECT {_PASSAGE_COLUMNS}, {distance} AS distance "
            "  FROM chunk_embeddings e "
            "  JOIN chunks c ON c.id = e.chunk_id JOIN judgments j ON j.id = c.judgment_id "
            f"  WHERE e.model_id = {_literal(model_id)} "
            f"  AND e.model_revision = {_literal(model_revision)} "
            f"  AND e.context_hash = {CONTEXT_HASH_SQL} AND {where} "
            f"  ORDER BY {distance} LIMIT :raw"
            "), unique_passages AS ("
            "  SELECT DISTINCT ON (nn.source_text_hash, nn.content_hash) nn.* FROM nn "
            "  ORDER BY nn.source_text_hash, nn.content_hash, nn.distance, nn.canonical_uri,"
            "  nn.chunk_id"
            "), ranked AS ("
            "  SELECT u.*, row_number() OVER ("
            "    PARTITION BY u.source_text_hash ORDER BY u.distance, u.chunk_id"
            "  ) AS case_rank FROM unique_passages u"
            ") "
            "SELECT * FROM ranked WHERE case_rank <= :per_case "
            "ORDER BY distance, chunk_id LIMIT :limit"
        ),
        params,
    )
    return [(_passage(row, 0.0), 1.0 - float(row.distance)) for row in rows]


def leading_passages(
    conn: Connection, judgment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PassageRow]:
    """The first chunk of each judgment (used for citation/case-name hits)."""
    if not judgment_ids:
        return {}
    rows = conn.execute(
        text(
            f"SELECT {_PASSAGE_COLUMNS} FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            "WHERE c.judgment_id = ANY(:ids) AND c.ordinal = 0"
        ),
        {"ids": judgment_ids},
    )
    return {row.judgment_id: _passage(row, 0.0) for row in rows}


def closing_passages(conn: Connection, judgment_id: uuid.UUID, count: int) -> list[PassageRow]:
    """The last ``count`` chunks of an eligible judgment, in reading order. A judgment's
    decision and orders are usually at its end; the leading chunk only names the parties."""
    rows = conn.execute(
        text(
            f"SELECT {_PASSAGE_COLUMNS} FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            "WHERE c.judgment_id = :id AND c.ordinal > 0 AND j.eligibility_status = :eligible "
            "ORDER BY c.ordinal DESC LIMIT :count"
        ),
        {"id": judgment_id, "count": count, "eligible": EligibilityStatus.ELIGIBLE.value},
    )
    return [_passage(row, 0.0) for row in reversed(rows.all())]


def text_twins(
    conn: Connection, text_hashes: list[str], filters: SearchFilters
) -> dict[str, list[JudgmentRow]]:
    """All eligible judgments (within the filters) that publish each source text."""
    if not text_hashes:
        return {}
    params: dict[str, Any] = {"hashes": text_hashes}
    where = filter_sql(filters, params)
    rows = conn.execute(
        text(
            f"SELECT DISTINCT c.source_text_hash, {_JUDGMENT_COLUMNS} "
            "FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            f"WHERE c.source_text_hash = ANY(:hashes) AND c.ordinal = 0 AND {where} "
            "ORDER BY c.source_text_hash, j.judgment_date, j.canonical_uri"
        ),
        params,
    )
    twins: dict[str, list[JudgmentRow]] = {}
    for row in rows:
        twins.setdefault(row.source_text_hash, []).append(_judgment(row))
    return twins


def judgment_detail(conn: Connection, judgment_id: uuid.UUID) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            f"SELECT {_JUDGMENT_COLUMNS}, j.case_number, j.language, j.judges, "
            "j.neutral_citation, j.source_status, "
            "(SELECT count(*) FROM chunks c WHERE c.judgment_id = j.id) AS chunk_count "
            "FROM judgments j WHERE j.id = :id AND j.eligibility_status = :eligible"
        ),
        {"id": judgment_id, "eligible": EligibilityStatus.ELIGIBLE.value},
    ).one_or_none()
    if row is None:
        return None
    sources = conn.execute(
        text(
            "SELECT kind, mime_type, verification_status, rights_status, original_url "
            "FROM document_sources WHERE judgment_id = :id ORDER BY kind"
        ),
        {"id": judgment_id},
    ).mappings()
    return {"judgment": _judgment(row), "row": row, "sources": [dict(s) for s in sources]}

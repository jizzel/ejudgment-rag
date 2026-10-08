"""Lexical retrieval: exact citation and case-name lookup plus full-text passage search.

Results come back two ways (AGENTS.md): ranked passages, and distinct cases. A judgment
re-published under several URIs is one case (grouped by its source text hash). Exact
citation matches rank first, then case-name matches, then full-text relevance.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Table, insert
from sqlalchemy.engine import Connection

from ejudgment.config import Settings
from ejudgment.domain.models import QueryAudit
from ejudgment.domain.schemas import (
    CaseResult,
    JudgmentDetail,
    JudgmentRef,
    MatchType,
    PassageResult,
    QueryInfo,
    SearchRequest,
    SearchResponse,
    SourceInfo,
)
from ejudgment.ingestion.hashing import sha256_text
from ejudgment.retrieval import repository as repo
from ejudgment.retrieval.query import names_every_party, parse_query

AUDIT = cast(Table, QueryAudit.__table__)
_MAX_CANDIDATES = 600
_MATCH_RANK: dict[MatchType, int] = {"citation": 0, "case_name": 1, "lexical": 2}


def _ref(row: repo.JudgmentRow, settings: Settings) -> JudgmentRef:
    return JudgmentRef(
        judgment_id=row.judgment_id,
        canonical_uri=row.canonical_uri,
        citation=row.citation,
        title=row.title,
        court_code=row.court_code,
        court_name=row.court_name,
        jurisdiction=row.jurisdiction,
        judgment_date=row.judgment_date,
        source_url=f"{settings.source_base_url.rstrip('/')}{row.canonical_uri}",
    )


def _passage(row: repo.PassageRow, match: MatchType, settings: Settings) -> PassageResult:
    verified = row.page_reference_status == "verified"
    return PassageResult(
        chunk_id=row.chunk_id,
        judgment=_ref(row.judgment, settings),
        excerpt=row.content,
        section_label=row.section_label,
        paragraph_refs=row.paragraph_refs,
        page_reference_status=row.page_reference_status,
        page_start=row.page_start if verified else None,
        page_end=row.page_end if verified else None,
        match_type=match,
        lexical_score=round(row.score, 6),
    )


@dataclass
class _Case:
    key: str
    judgment: repo.JudgmentRow
    match: MatchType
    score: float
    passages: list[tuple[repo.PassageRow, MatchType]]

    def add(self, row: repo.PassageRow, match: MatchType) -> bool:
        """Add a passage unless the case already has it or is full."""
        if any(existing.content_hash == row.content_hash for existing, _ in self.passages):
            return False
        self.passages.append((row, match))
        return True


def search(conn: Connection, request: SearchRequest, settings: Settings) -> SearchResponse:
    parsed = parse_query(request.query)
    filters = request.filters
    wanted = request.offset + request.top_k
    cases: dict[str, _Case] = {}
    passages: list[tuple[repo.PassageRow, MatchType]] = []

    def add_exact(judgments: list[tuple[repo.JudgmentRow, float]], match: MatchType) -> None:
        leading = repo.leading_passages(conn, [row.judgment_id for row, _ in judgments])
        for row, score in judgments:
            passage = leading.get(row.judgment_id)
            key = passage.source_text_hash if passage else f"judgment:{row.judgment_id}"
            if key in cases:
                continue
            cases[key] = _Case(key, row, match, score, [])
            if passage is not None and cases[key].add(passage, match):
                passages.append((passage, match))

    if parsed.neutral_citation is not None:
        hits = repo.citation_matches(conn, parsed.neutral_citation, filters)
        add_exact([(row, 1.0) for row in hits], "citation")
    if parsed.looks_like_case_name:
        candidates = repo.case_name_matches(conn, parsed.text, filters, wanted * 5)
        named = [
            (row, sim) for row, sim in candidates if names_every_party(parsed.text, row.citation)
        ]
        add_exact(named[:wanted], "case_name")

    # Candidates arrive already capped per case, so this many rows covers `wanted` cases even
    # when exact matches take some of them.
    limit = min(_MAX_CANDIDATES, max(wanted * settings.passages_per_case * 2, 50))
    for row in repo.lexical_passages(conn, parsed.text, filters, limit, settings.passages_per_case):
        # Cases are whole source texts: a passage shared by *different* judgments (a quoted
        # statute, say) still yields a case for each; re-publications collapse into one.
        case = cases.get(row.source_text_hash)
        if case is None:
            case = _Case(row.source_text_hash, row.judgment, "lexical", row.score, [])
            cases[row.source_text_hash] = case
        if len(case.passages) >= settings.passages_per_case:
            continue
        if case.add(row, "lexical"):
            passages.append((row, "lexical"))

    ranked_cases = sorted(
        cases.values(), key=lambda c: (_MATCH_RANK[c.match], -c.score, c.judgment.canonical_uri)
    )[request.offset : wanted]
    ranked_passages = sorted(
        passages,
        key=lambda p: (_MATCH_RANK[p[1]], -p[0].score, str(p[0].chunk_id)),
    )[request.offset : wanted]

    twin_keys = [c.key for c in ranked_cases if not c.key.startswith("judgment:")]
    twins = repo.text_twins(conn, twin_keys, filters)
    case_results = []
    for case in ranked_cases:
        others = [
            _ref(row, settings)
            for row in twins.get(case.key, [])
            if row.judgment_id != case.judgment.judgment_id
        ]
        case_results.append(
            CaseResult(
                judgment=_ref(case.judgment, settings),
                also_published_as=others,
                match_type=case.match,
                score=round(case.score, 6),
                passages=[_passage(row, match, settings) for row, match in case.passages],
            )
        )
    return SearchResponse(
        query=request.query,
        passages=[_passage(row, match, settings) for row, match in ranked_passages],
        cases=case_results,
        query_info=QueryInfo(
            detected_citation=str(parsed.neutral_citation) if parsed.neutral_citation else None,
            looks_like_case_name=parsed.looks_like_case_name,
            filters_applied=filters.applied(),
        ),
    )


def get_judgment(
    conn: Connection, judgment_id: uuid.UUID, settings: Settings
) -> JudgmentDetail | None:
    detail = repo.judgment_detail(conn, judgment_id)
    if detail is None:
        return None
    row = detail["row"]
    return JudgmentDetail(
        judgment=_ref(detail["judgment"], settings),
        case_number=row.case_number,
        language=row.language,
        judges=[str(judge) for judge in row.judges],
        neutral_citation=row.neutral_citation,
        source_status=row.source_status,
        sources=[SourceInfo(**source) for source in detail["sources"]],
        chunk_count=row.chunk_count,
    )


def record_audit(
    conn: Connection,
    request: SearchRequest,
    response: SearchResponse,
    started: float,
    settings: Settings,
    endpoint: str,
) -> None:
    """Hashed by default; raw query text only when AUDIT_STORE_RAW_QUERIES=true."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "endpoint": endpoint,
        "query_hash": sha256_text(request.query),
        "query_text": request.query if settings.audit_store_raw_queries else None,
        "filters": request.filters.applied(),
        "result_judgment_ids": [str(case.judgment.judgment_id) for case in response.cases],
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    conn.execute(insert(AUDIT).values(**values))

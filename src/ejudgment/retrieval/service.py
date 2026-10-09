"""Retrieval: exact citation and case-name lookup, then lexical, dense or hybrid passages.

Results come back two ways (AGENTS.md): ranked passages, and distinct cases. A judgment
re-published under several URIs is one case (grouped by its source text hash). Exact
citation matches rank first, then case-name matches, then the (reranked) channel ranking.
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
    ContextPassage,
    CourtInfo,
    CourtsResponse,
    JudgmentDetail,
    JudgmentRef,
    MatchType,
    PassageContext,
    PassageResult,
    QueryInfo,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SourceInfo,
)
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.ingestion.hashing import sha256_text
from ejudgment.retrieval import repository as repo
from ejudgment.retrieval.coverage import embedding_coverage
from ejudgment.retrieval.hybrid import Candidate, apply_rerank, from_dense, from_lexical, rrf_fuse
from ejudgment.retrieval.query import parse_query

AUDIT = cast(Table, QueryAudit.__table__)


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


class SearchDepthExceeded(ValueError):
    """offset + top_k goes beyond the fixed candidate pools (search_max_depth)."""


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _passage(candidate: Candidate, match: MatchType, settings: Settings) -> PassageResult:
    row = candidate.row
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
        lexical_score=_round(candidate.lexical_score),
        dense_score=_round(candidate.dense_score),
        rrf_score=_round(candidate.rrf_score),
        rerank_score=_round(candidate.rerank_score),
    )


def _final_score(candidate: Candidate) -> float:
    for score in (
        candidate.rerank_score,
        candidate.rrf_score,
        candidate.lexical_score,
        candidate.dense_score,
    ):
        if score is not None:
            return score
    return 0.0


def _channel_match(candidate: Candidate) -> MatchType:
    if candidate.lexical_rank is not None and candidate.dense_rank is not None:
        return "hybrid"
    return "dense" if candidate.dense_rank is not None else "lexical"


@dataclass
class _Case:
    key: str
    judgment: repo.JudgmentRow
    match: MatchType
    score: float
    passages: list[tuple[Candidate, MatchType]]

    def add(self, candidate: Candidate, match: MatchType) -> bool:
        """Add a passage unless the case already has the same text."""
        content_hash = candidate.row.content_hash
        if any(existing.row.content_hash == content_hash for existing, _ in self.passages):
            return False
        self.passages.append((candidate, match))
        return True


def search(
    conn: Connection,
    request: SearchRequest,
    settings: Settings,
    *,
    embedder: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
) -> SearchResponse:
    """Exact citation and case-name matches first, then channel results.

    The lexical and dense pools have a fixed size (``hybrid_channel_k`` passages, at most
    ``passages_per_case`` per case), independent of the offset: every page is a slice of the
    same final ranking, so pages neither overlap nor skip cases. That bounds paging depth to
    ``search_max_depth`` cases.
    """
    wanted = request.offset + request.top_k
    if wanted > settings.search_max_depth:
        raise SearchDepthExceeded(
            f"offset + top_k must be <= {settings.search_max_depth} (got {wanted})"
        )
    parsed = parse_query(request.query)
    filters = request.filters
    per_case = settings.passages_per_case
    cases: dict[str, _Case] = {}
    passages: list[tuple[Candidate, MatchType]] = []

    def add_exact(judgments: list[tuple[repo.JudgmentRow, float]], match: MatchType) -> None:
        leading = repo.leading_passages(conn, [row.judgment_id for row, _ in judgments])
        for row, score in judgments:
            passage = leading.get(row.judgment_id)
            key = passage.source_text_hash if passage else f"judgment:{row.judgment_id}"
            if key in cases:
                continue
            cases[key] = _Case(key, row, match, score, [])
            if passage is not None:
                candidate = Candidate(passage)
                if cases[key].add(candidate, match):
                    passages.append((candidate, match))

    if parsed.neutral_citation is not None:
        hits = repo.citation_matches(conn, parsed.neutral_citation, filters)
        add_exact([(row, 1.0) for row in hits], "citation")
    if parsed.looks_like_case_name:
        add_exact(repo.case_name_matches(conn, parsed.text, filters, wanted), "case_name")

    mode_used = request.mode
    degraded: list[str] = []
    if mode_used != "lexical" and embedder is None:
        mode_used = "lexical"
        degraded.append("embedding model unavailable; used lexical retrieval")
    elif mode_used != "lexical" and embedder is not None:
        # A loaded model is not enough: its vectors must exist for the searchable chunks.
        coverage = embedding_coverage(
            conn,
            embedder.model_id,
            embedder.model_revision,
            settings.embedding_coverage_ttl_seconds,
        )
        label = f"{embedder.model_id}@{embedder.model_revision[:12]}"
        if coverage.total and not coverage.embedded:
            mode_used = "lexical"
            degraded.append(
                f"no embeddings stored for {label}; used lexical retrieval (run worker.embed)"
            )
        elif coverage.missing:
            degraded.append(
                f"embeddings missing for {coverage.missing} of {coverage.total} chunks "
                f"({label}); dense results are incomplete"
            )

    # Fixed per request settings (never dependent on the offset), and deep enough that the
    # per-case-capped pool always covers search_max_depth cases.
    k = max(settings.hybrid_channel_k, settings.search_max_depth * per_case)
    lexical = (
        repo.lexical_passages(conn, parsed.text, filters, k, per_case)
        if mode_used in ("lexical", "hybrid")
        else []
    )
    dense: list[tuple[repo.PassageRow, float]] = []
    if mode_used in ("dense", "hybrid") and embedder is not None:
        dense = repo.dense_passages(
            conn,
            embedder.embed_query(parsed.text),
            model_id=embedder.model_id,
            model_revision=embedder.model_revision,
            dimension=embedder.dimension,
            filters=filters,
            limit=k,
            per_case=per_case,
            ef_search=settings.hnsw_ef_search,
            raw_neighbours=settings.dense_raw_neighbours,
        )
    if mode_used == "hybrid":
        candidates = rrf_fuse(lexical, dense, settings.rrf_k)
    elif mode_used == "lexical":
        candidates = from_lexical(lexical)
    else:
        candidates = from_dense(dense)

    reranked = False
    if request.rerank and candidates:
        if reranker is None:
            degraded.append("reranker unavailable; results not reranked")
        else:
            head = candidates[: settings.rerank_top_n]
            scores = reranker.score(parsed.text, [c.row.content for c in head])
            candidates = apply_rerank(candidates, scores)
            reranked = True

    for candidate in candidates:
        # Cases are whole source texts: a passage shared by *different* judgments (a quoted
        # statute, say) still yields a case for each; re-publications collapse into one.
        row = candidate.row
        match = _channel_match(candidate)
        case = cases.get(row.source_text_hash)
        if case is None:
            case = _Case(row.source_text_hash, row.judgment, match, _final_score(candidate), [])
            cases[row.source_text_hash] = case
        if len(case.passages) >= per_case:
            continue
        if case.add(candidate, match):
            passages.append((candidate, match))

    # Stable sorts: within a match class, everything keeps its final-ranking position.
    exact_first = {"citation": 0, "case_name": 1}
    ranked_cases = sorted(cases.values(), key=lambda c: exact_first.get(c.match, 2))[
        request.offset : wanted
    ]
    ranked_passages = sorted(passages, key=lambda p: exact_first.get(p[1], 2))[
        request.offset : wanted
    ]

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
                passages=[_passage(c, match, settings) for c, match in case.passages],
            )
        )
    return SearchResponse(
        query=request.query,
        passages=[_passage(c, match, settings) for c, match in ranked_passages],
        cases=case_results,
        query_info=QueryInfo(
            detected_citation=str(parsed.neutral_citation) if parsed.neutral_citation else None,
            looks_like_case_name=parsed.looks_like_case_name,
            filters_applied=filters.applied(),
            mode_requested=request.mode,
            mode_used=mode_used,
            reranked=reranked,
            degraded=bool(degraded),
            degraded_reason="; ".join(degraded) or None,
        ),
    )


def closing_passages(
    conn: Connection, case: CaseResult, count: int, settings: Settings
) -> list[PassageResult]:
    """The final passages of a case's judgment, matched the way the case was."""
    rows = repo.closing_passages(conn, case.judgment.judgment_id, count)
    return [_passage(Candidate(row), case.match_type, settings) for row in rows]


def passage_context(
    conn: Connection, chunk_id: uuid.UUID, context: int, settings: Settings
) -> PassageContext | None:
    rows = repo.passage_context(conn, chunk_id, context)
    if rows is None:
        return None

    def item(ordinal: int, row: repo.PassageRow) -> ContextPassage:
        verified = row.page_reference_status == "verified"
        return ContextPassage(
            chunk_id=row.chunk_id,
            ordinal=ordinal,
            excerpt=row.content,
            section_label=row.section_label,
            page_reference_status=row.page_reference_status,
            page_start=row.page_start if verified else None,
            page_end=row.page_end if verified else None,
        )

    index = next(i for i, (_, row) in enumerate(rows) if row.chunk_id == chunk_id)
    return PassageContext(
        judgment=_ref(rows[index][1].judgment, settings),
        passage=item(*rows[index]),
        before=[item(*pair) for pair in rows[:index]],
        after=[item(*pair) for pair in rows[index + 1 :]],
    )


def list_courts(conn: Connection) -> CourtsResponse:
    return CourtsResponse(
        courts=[
            CourtInfo(court_code=code, court_name=name, judgments=count)
            for code, name, count in repo.courts(conn)
        ]
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
    query: str,
    filters: SearchFilters,
    judgment_ids: list[uuid.UUID],
    started: float,
    settings: Settings,
    endpoint: str,
) -> None:
    """Hashed by default; raw query text only when AUDIT_STORE_RAW_QUERIES=true."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "endpoint": endpoint,
        "query_hash": sha256_text(query),
        "query_text": query if settings.audit_store_raw_queries else None,
        "filters": filters.applied(),
        "result_judgment_ids": [str(judgment_id) for judgment_id in judgment_ids],
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
    conn.execute(insert(AUDIT).values(**values))

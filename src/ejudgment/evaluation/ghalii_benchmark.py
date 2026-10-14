"""Benchmark against GhaLII's own site search (docs/benchmark-ghalii.md).

GhaLII prohibits scraping, so its side is searched by hand in a browser and recorded in a
CSV sheet: for each gold question and query arm, the rank (1-20) of the first gold case in
GhaLII's results and that result's URL, or ``none``. This module writes the sheets, checks
and scores what was recorded, and pairs it with our own search on the same query strings.
Nothing here contacts GhaLII.

Arms: ``verbatim`` searches the gold question as written; ``keywords`` searches the keyword
query someone wrote for it *before* seeing either system's results or the gold answers.
"""

import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ejudgment.domain.schemas import SearchFilters, SearchResponse
from ejudgment.evaluation.retrieval import MRR_AT, RECALL_AT, GoldQuestion
from ejudgment.ingestion.normalize import parse_akn_uri

Arm = Literal["verbatim", "keywords"]
ARMS: tuple[Arm, ...] = ("verbatim", "keywords")
NONE = "none"

QUERY_COLUMNS = ("id", "category", "question", "filters", "keyword_query")
SHEET_COLUMNS = (
    "id",
    "category",
    "question",
    "keyword_query",
    "filters_to_apply",
    "filters",  # the gold filters as JSON: scoring checks them against the current gold set
    "look_for",
    "verbatim_rank",
    "verbatim_url",
    "verbatim_result_count",
    "keywords_rank",
    "keywords_url",
    "keywords_result_count",
    "searched_on",
    "notes",
)


@dataclass(frozen=True)
class CaseCopy:
    canonical_uri: str
    citation: str


# --- preparing the sheets -------------------------------------------------------------


def filters_json(question: GoldQuestion) -> str:
    return json.dumps(question.filters.applied(), sort_keys=True)


def _open_for_writing(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", newline="", encoding="utf-8")


def write_query_sheet(questions: list[GoldQuestion], path: Path) -> None:
    """Step 1, for the query writer: questions and filters only (no gold cases), with an
    empty ``keyword_query`` column to fill."""
    with _open_for_writing(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=QUERY_COLUMNS)
        writer.writeheader()
        for q in questions:
            writer.writerow(
                {
                    "id": q.id,
                    "category": q.category,
                    "question": q.question,
                    "filters": filters_json(q),
                    "keyword_query": "",
                }
            )


def read_keyword_queries(path: Path, questions: list[GoldQuestion]) -> dict[str, str]:
    """The filled query sheet: one non-empty keyword query for every gold question."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    queries = {row["id"]: (row.get("keyword_query") or "").strip() for row in rows}
    problems = [f"{q.id}: no keyword query" for q in questions if not queries.get(q.id)]
    problems += [f"{i}: not a gold question" for i in queries if i not in {q.id for q in questions}]
    if problems:
        raise ValueError("; ".join(problems))
    return queries


def case_copies(conn: Connection, uris: list[str]) -> dict[str, list[CaseCopy]]:
    """Each gold URI with every URI publishing the same text (the case's re-publications),
    citations included: any of them counts as finding the case, on either side."""
    copies: dict[str, list[CaseCopy]] = {}
    for uri in uris:
        rows = conn.execute(
            text(
                "SELECT j.canonical_uri, j.citation FROM judgments j WHERE j.canonical_uri = :u"
                " UNION SELECT j.canonical_uri, j.citation FROM judgments j"
                " JOIN chunks c ON c.judgment_id = j.id WHERE c.source_text_hash IN"
                " (SELECT c2.source_text_hash FROM chunks c2 JOIN judgments j2"
                "  ON j2.id = c2.judgment_id WHERE j2.canonical_uri = :u)"
                " ORDER BY 1"
            ),
            {"u": uri},
        ).all()
        copies[uri] = [CaseCopy(r.canonical_uri, r.citation or r.canonical_uri) for r in rows]
    return copies


def describe_filters(filters: SearchFilters, court_names: dict[str, str]) -> str:
    """The question's filters as GhaLII facets a person can set by hand."""
    parts = []
    if filters.court:
        parts.append(f"Court: {court_names.get(filters.court, filters.court)}")
    if filters.year_from or filters.year_to:
        parts.append(f"Years: {filters.year_from or 'any'}-{filters.year_to or 'any'}")
    if filters.judge:
        parts.append(f"Judge: {filters.judge}")
    if filters.jurisdiction:
        parts.append(f"Jurisdiction: {filters.jurisdiction}")
    return "; ".join(parts)


def look_for(question: GoldQuestion, copies: dict[str, list[CaseCopy]]) -> str:
    """What the recorder looks for in GhaLII's results: every citation that counts."""
    if question.expect_no_answer:
        return "(outside the corpus: record only the result count)"
    found = {
        c.canonical_uri: c.citation
        for uri in question.gold_canonical_uris
        for c in copies.get(uri, [])
    }
    return " | ".join(f"{citation} ({uri})" for uri, citation in sorted(found.items()))


def write_recording_sheet(
    questions: list[GoldQuestion],
    keyword_queries: dict[str, str],
    copies: dict[str, list[CaseCopy]],
    court_names: dict[str, str],
    path: Path,
) -> None:
    """Step 2, for the recorder: both queries, the facets to set and the cases to look for."""
    with _open_for_writing(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for q in questions:
            row = dict.fromkeys(SHEET_COLUMNS, "")
            row.update(
                id=q.id,
                category=q.category,
                question=q.question,
                keyword_query=keyword_queries[q.id],
                filters_to_apply=describe_filters(q.filters, court_names),
                filters=filters_json(q),
                look_for=look_for(q, copies),
            )
            writer.writerow(row)


# --- reading and checking what was recorded -------------------------------------------


@dataclass(frozen=True)
class Recorded:
    question_id: str
    arm: Arm
    query: str
    rank: int | None  # None: no gold case in the first RECALL_AT results
    url: str | None
    result_count: int | None
    searched_on: str


def accepted_paths(copies: list[CaseCopy]) -> set[str]:
    """Expression and work paths of every copy: GhaLII may link either form."""
    paths: set[str] = set()
    for copy in copies:
        paths.add(copy.canonical_uri)
        identity = parse_akn_uri(copy.canonical_uri)
        if identity:
            paths.add(identity.work_uri)
    return paths


def url_path(url: str) -> str:
    return urlsplit(url.strip()).path.rstrip("/")


def read_recording_sheet(
    path: Path, questions: list[GoldQuestion], copies: dict[str, list[CaseCopy]]
) -> list[Recorded]:
    """Every row and arm must be filled: a rank 1-20 with the URL of a gold case (or one of
    its re-publications), or ``none`` with no URL. Problems are collected and raised together,
    so a recorder can fix the sheet in one pass."""
    by_id = {q.id: q for q in questions}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    problems: list[str] = []
    recorded: list[Recorded] = []
    seen: set[str] = set()
    for row in rows:
        qid = row.get("id", "")
        question = by_id.get(qid)
        if question is None:
            problems.append(f"{qid}: not a gold question")
            continue
        if qid in seen:
            problems.append(f"{qid}: appears more than once")
            continue
        seen.add(qid)
        # The sheet must describe the question as it is now: our side searches the current
        # text and filters, GhaLII's rank was recorded for the sheet's.
        if (row.get("question") or "").strip() != question.question.strip():
            problems.append(f"{qid}: question changed since the sheet was made; record it again")
            continue
        if (row.get("filters") or "").strip() != filters_json(question):
            problems.append(f"{qid}: filters changed since the sheet was made; record it again")
            continue
        accepted = set().union(
            *(accepted_paths(copies.get(u, [])) for u in question.gold_canonical_uris)
        )
        for arm in ARMS:
            where = f"{qid} {arm}"
            raw_rank = (row.get(f"{arm}_rank") or "").strip().lower()
            url = (row.get(f"{arm}_url") or "").strip() or None
            raw_count = (row.get(f"{arm}_result_count") or "").strip().replace(",", "")
            count = int(raw_count) if raw_count.isdigit() else None
            if raw_count and count is None:
                problems.append(f"{where}: result count {raw_count!r} is not a number")
            rank: int | None = None
            if question.expect_no_answer:
                if count is None:
                    problems.append(f"{where}: record the result count")
                if raw_rank or url:
                    problems.append(f"{where}: no rank or URL for an out-of-corpus question")
            elif raw_rank == NONE:
                if url:
                    problems.append(f"{where}: rank 'none' but a URL was given")
            elif raw_rank.isdigit() and 1 <= int(raw_rank) <= RECALL_AT:
                rank = int(raw_rank)
                if not url:
                    problems.append(f"{where}: rank {rank} needs the result's URL")
                elif url_path(url) not in accepted:
                    problems.append(f"{where}: {url} is not a gold case of this question")
            else:
                problems.append(f"{where}: rank must be 1-{RECALL_AT} or '{NONE}'")
            query = question.question if arm == "verbatim" else (row.get("keyword_query") or "")
            recorded.append(
                Recorded(qid, arm, query.strip(), rank, url, count, row.get("searched_on", ""))
            )
    problems += [f"{q.id}: missing from the sheet" for q in questions if q.id not in seen]
    if problems:
        raise ValueError("\n".join(problems))
    return recorded


# --- our side and scoring -------------------------------------------------------------


def our_rank(response: SearchResponse, copies: list[CaseCopy]) -> int | None:
    """Rank of the first returned case that is (or re-publishes) a gold case."""
    gold = {c.canonical_uri for c in copies}
    for rank, case in enumerate(response.cases, 1):
        uris = {case.judgment.canonical_uri} | {r.canonical_uri for r in case.also_published_as}
        if uris & gold:
            return rank
    return None


def _hit(rank: int | None) -> bool:
    return rank is not None and rank <= RECALL_AT


def _reciprocal(rank: int | None) -> float:
    return 1.0 / rank if rank is not None and rank <= MRR_AT else 0.0


def mcnemar_p(only_a: int, only_b: int) -> float:
    """Exact two-sided McNemar test on the discordant pairs (binomial, p=0.5)."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(only_a, only_b) + 1)) / (1 << n)
    return min(1.0, 2 * tail)


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per arm: each system's Recall@20 / MRR@10 overall and by category, and the paired
    comparison over the same questions (who found the gold case when the other did not)."""
    out: dict[str, Any] = {}
    for arm in ARMS:
        rows = [r for r in records if r["arm"] == arm and not r["expect_no_answer"]]
        if not rows:
            continue
        arm_out: dict[str, Any] = {"answerable_questions": len(rows)}
        for system in ("ghalii", "ours"):
            by_category: dict[str, list[float]] = defaultdict(list)
            for r in rows:
                by_category[r["category"]].append(1.0 if _hit(r[f"{system}_rank"]) else 0.0)
            arm_out[system] = {
                f"recall@{RECALL_AT}": round(
                    statistics.fmean(1.0 if _hit(r[f"{system}_rank"]) else 0.0 for r in rows), 4
                ),
                f"mrr@{MRR_AT}": round(
                    statistics.fmean(_reciprocal(r[f"{system}_rank"]) for r in rows), 4
                ),
                "recall_by_category": {
                    c: round(statistics.fmean(v), 4) for c, v in sorted(by_category.items())
                },
            }
        only_ours = sum(_hit(r["ours_rank"]) and not _hit(r["ghalii_rank"]) for r in rows)
        only_ghalii = sum(_hit(r["ghalii_rank"]) and not _hit(r["ours_rank"]) for r in rows)
        arm_out["paired"] = {
            "both": sum(_hit(r["ours_rank"]) and _hit(r["ghalii_rank"]) for r in rows),
            "only_ours": only_ours,
            "only_ghalii": only_ghalii,
            "neither": sum(not _hit(r["ours_rank"]) and not _hit(r["ghalii_rank"]) for r in rows),
            "mcnemar_p": round(mcnemar_p(only_ours, only_ghalii), 4),
        }
        none_rows = [r for r in records if r["arm"] == arm and r["expect_no_answer"]]
        arm_out["out_of_corpus"] = {
            "questions": len(none_rows),
            "ghalii_result_counts": {r["id"]: r["ghalii_result_count"] for r in none_rows},
        }
        out[arm] = arm_out
    return out

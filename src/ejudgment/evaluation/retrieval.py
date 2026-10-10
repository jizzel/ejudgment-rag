"""Retrieval evaluation against ``evals/gold.jsonl``.

Case-level metrics: a question is answered when any of its gold judgments (by canonical
URI, counting every URI a case is also published as) appears among the returned cases.
Recall@20 and MRR@10 cover answerable questions; ``expect_no_answer`` questions are
reported separately (what came back, and how confidently), since abstention belongs to
generation (M3). Metrics on ``reviewed=false`` questions are provisional.
"""

import json
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, Table, insert, text
from sqlalchemy.engine import Connection

from ejudgment.config import Settings
from ejudgment.domain.models import EvaluationRun
from ejudgment.domain.schemas import SearchFilters, SearchMode, SearchRequest, SearchResponse
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.embeddings.template import TEMPLATE_VERSION
from ejudgment.ingestion.hashing import sha256_file
from ejudgment.retrieval.service import search
from ejudgment.verification.support import normalise

RUNS = cast(Table, EvaluationRun.__table__)
RECALL_AT = 20
MRR_AT = 10

Category = Literal["citation", "case_name", "issue", "fact_pattern", "out_of_corpus"]


class GoldPassage(BaseModel):
    """A passage that answers the question, as verbatim text of one of the gold judgments
    (text, not a chunk id: it survives re-chunking)."""

    model_config = ConfigDict(extra="forbid")

    canonical_uri: str
    text: str = Field(min_length=20, max_length=5000)


class GoldQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    question: str = Field(min_length=1, max_length=1000)
    category: Category
    filters: SearchFilters = Field(default_factory=SearchFilters)
    gold_canonical_uris: list[str] = Field(default_factory=list)
    gold_passages: list[GoldPassage] = Field(default_factory=list)
    expect_no_answer: bool = False
    reviewed: bool = False
    reviewed_at: datetime | None = None
    notes: str | None = None


def gold_problems(question: GoldQuestion) -> list[str]:
    """What keeps a question from being a valid gold question (empty when valid). Used by the
    loader and by approval in the review workflow."""
    problems: list[str] = []
    if question.expect_no_answer == bool(question.gold_canonical_uris):
        problems.append("give gold_canonical_uris or expect_no_answer, not both")
    uris = set(question.gold_canonical_uris)
    for passage in question.gold_passages:
        if passage.canonical_uri not in uris:
            problems.append(f"gold passage from a case that is not gold: {passage.canonical_uri}")
    if question.reviewed_at is not None and not question.reviewed:
        problems.append("reviewed_at is only for reviewed questions")
    return problems


@dataclass(frozen=True)
class EvalConfig:
    name: str
    mode: SearchMode
    rerank: bool


DEFAULT_CONFIGS = (
    EvalConfig("lexical", "lexical", False),
    EvalConfig("dense", "dense", False),
    EvalConfig("hybrid", "hybrid", False),
    EvalConfig("hybrid+rerank", "hybrid", True),
)


def load_gold(path: Path) -> list[GoldQuestion]:
    questions = [
        GoldQuestion.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids in gold set")
    for question in questions:
        problems = gold_problems(question)
        if problems:
            raise ValueError(f"{question.id}: {'; '.join(problems)}")
    return questions


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def evaluate(
    engine: Engine,
    settings: Settings,
    questions: list[GoldQuestion],
    *,
    embedder: EmbeddingProvider | None,
    reranker: Reranker | None,
    configs: tuple[EvalConfig, ...] = DEFAULT_CONFIGS,
    warmup: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Latencies are warm-cache figures when ``warmup`` (one untimed hybrid pass over every
    question first), so run order and earlier table scans do not skew them."""
    per_question: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    with engine.connect() as conn:
        if warmup:
            for question in questions:
                warm = SearchRequest(
                    query=question.question, filters=question.filters, top_k=RECALL_AT
                )
                search(conn, warm, settings, embedder=embedder, reranker=reranker)
        for config in configs:
            records: list[dict[str, Any]] = []
            for question in questions:
                request = SearchRequest(
                    query=question.question,
                    filters=question.filters,
                    top_k=RECALL_AT,
                    mode=config.mode,
                    rerank=config.rerank,
                )
                started = time.perf_counter()
                response = search(conn, request, settings, embedder=embedder, reranker=reranker)
                latency = (time.perf_counter() - started) * 1000
                records.append(_record(config, question, response, latency))
            per_question.extend(records)
            summary = summarise_retrieval(records, warmup=warmup)
            reviewed = [r for r in records if r["reviewed"]]
            summary["reviewed"] = summarise_retrieval(reviewed, warmup=warmup) if reviewed else None
            metrics[config.name] = summary
    return metrics, per_question


def passage_hit(question: GoldQuestion, excerpts: list[str]) -> bool | None:
    """Whether a returned passage overlaps a gold passage (normalised text containment either
    way: a gold passage may span chunks, or sit inside one). None without gold passages."""
    if not question.gold_passages:
        return None
    gold = [normalise(passage.text) for passage in question.gold_passages]
    returned = [normalise(excerpt) for excerpt in excerpts]
    return any(g in r or r in g for g in gold for r in returned if r)


def _record(
    config: EvalConfig, question: GoldQuestion, response: SearchResponse, latency_ms: float
) -> dict[str, Any]:
    ranked = [
        {case.judgment.canonical_uri} | {ref.canonical_uri for ref in case.also_published_as}
        for case in response.cases
    ]
    gold = set(question.gold_canonical_uris)
    rank = next((i for i, uris in enumerate(ranked, 1) if uris & gold), None)
    record: dict[str, Any] = {
        "config": config.name,
        "id": question.id,
        "category": question.category,
        "reviewed": question.reviewed,
        "expect_no_answer": question.expect_no_answer,
        "rank": rank,
        "passage_hit": passage_hit(question, [p.excerpt for p in response.passages]),
        "degraded": response.query_info.degraded,
        "latency_ms": round(latency_ms, 1),
        "top": [case.judgment.canonical_uri for case in response.cases[:3]],
    }
    if question.expect_no_answer:
        top = response.passages[0] if response.passages else None
        record["returned_cases"] = len(response.cases)
        record["top_rerank_score"] = top.rerank_score if top else None
    return record


def summarise_retrieval(records: list[dict[str, Any]], *, warmup: bool) -> dict[str, Any]:
    answerable = [r for r in records if not r["expect_no_answer"]]
    hits = [1.0 if r["rank"] is not None and r["rank"] <= RECALL_AT else 0.0 for r in answerable]
    reciprocal = [
        1.0 / r["rank"] if r["rank"] is not None and r["rank"] <= MRR_AT else 0.0
        for r in answerable
    ]
    by_category: dict[str, list[float]] = defaultdict(list)
    for record, hit in zip(answerable, hits, strict=True):
        by_category[record["category"]].append(hit)
    passages = [r["passage_hit"] for r in answerable if r["passage_hit"] is not None]
    latencies = [r["latency_ms"] for r in records]
    return {
        f"recall@{RECALL_AT}": round(statistics.fmean(hits), 4) if hits else None,
        f"mrr@{MRR_AT}": round(statistics.fmean(reciprocal), 4) if reciprocal else None,
        f"passage_recall@{RECALL_AT}": (
            round(statistics.fmean(1.0 if hit else 0.0 for hit in passages), 4)
            if passages
            else None
        ),
        "latency_p50_ms": round(percentile(latencies, 0.5), 1) if latencies else None,
        "latency_p95_ms": round(percentile(latencies, 0.95), 1) if latencies else None,
        "recall_by_category": {
            category: round(statistics.fmean(values), 4)
            for category, values in sorted(by_category.items())
        },
        "questions": len(records),
        "answerable_questions": len(answerable),
        "questions_with_gold_passages": len(passages),
        "degraded": any(r["degraded"] for r in records),
        "latency_cache": "warm" if warmup else "as-is",
    }


VECTOR_INDEX_PREFIX = "ix_chunk_embeddings_hnsw_"

# Every setting that can change what retrieval returns or how it is ranked. A run records
# their effective values, so two runs with different results can be told apart.
RANKING_SETTINGS = (
    "embedding_model_id",
    "embedding_revision",
    "embedding_dimension",
    "embedding_max_input_tokens",
    "embedding_query_instruction",
    "model_device",
    "reranker_model_id",
    "reranker_revision",
    "reranker_max_input_tokens",
    "rerank_top_n",
    "tokenizer_model_id",
    "tokenizer_revision",
    "chunk_target_tokens",
    "chunk_max_tokens",
    "hybrid_channel_k",
    "rrf_k",
    "hnsw_ef_search",
    "dense_raw_neighbours",
    "search_max_depth",
    "passages_per_case",
)


def corpus_version(conn: Connection, embedder: EmbeddingProvider | None) -> dict[str, Any]:
    """Fingerprints of what was searched: eligible judgments, chunks, embeddings, indexes."""
    judgments = conn.execute(
        text(
            # Every column retrieval reads (exact citation and case-name matching, filters,
            # embedding context, eligibility) plus record_hash, which also covers the sources;
            # hashed per row so changes made outside the importer are caught too.
            "SELECT count(*) FILTER (WHERE eligibility_status = 'eligible') AS eligible, "
            "md5(string_agg(md5(ROW(id, eligibility_status, record_hash, citation, "
            "citation_normalized, neutral_citation, title, court_code, court_name, jurisdiction, "
            "judgment_date, judges)::text), ',' ORDER BY id)) AS digest FROM judgments"
        )
    ).one()
    chunks = conn.execute(
        text(
            "SELECT count(*) AS n, array_agg(DISTINCT chunker_version) AS versions, "
            "md5(string_agg(id::text || ':' || content_hash, ',' ORDER BY id)) AS digest "
            "FROM chunks"
        )
    ).one()
    version: dict[str, Any] = {
        "alembic_revision": conn.execute(text("SELECT version_num FROM alembic_version")).scalar(),
        "pgvector_version": conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar(),
        "eligible_judgments": judgments.eligible,
        "judgments_digest": judgments.digest,
        "chunks": chunks.n,
        "chunker_versions": sorted(chunks.versions or []),
        "chunks_digest": chunks.digest,
        "vector_indexes": {
            row.indexname: row.indexdef
            for row in conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'chunk_embeddings' ORDER BY indexname"
                )
            )
            if row.indexname.startswith(VECTOR_INDEX_PREFIX)
        },
    }
    if embedder is not None:
        embeddings = conn.execute(
            text(
                "SELECT count(*) AS n, "
                "array_agg(DISTINCT embedding_template_version) AS templates, "
                "md5(string_agg(chunk_id::text || ':' || embedding_input_hash, ',' "
                "ORDER BY chunk_id)) AS digest "
                "FROM chunk_embeddings WHERE model_id = :model AND model_revision = :revision"
            ),
            {"model": embedder.model_id, "revision": embedder.model_revision},
        ).one()
        version.update(
            embeddings=embeddings.n,
            embedding_templates=sorted(embeddings.templates or []),
            embeddings_digest=embeddings.digest,
        )
    return version


def run_config(
    engine: Engine,
    settings: Settings,
    gold_path: Path,
    questions: list[GoldQuestion],
    embedder: EmbeddingProvider | None,
    reranker: Reranker | None,
) -> dict[str, Any]:
    """Everything needed to reproduce or explain a run (AGENTS.md rule 4): the gold set,
    which models were actually loaded, every ranking setting, and the corpus/index version."""
    with engine.connect() as conn:
        corpus = corpus_version(conn, embedder)
    return {
        "gold_file": str(gold_path),
        "gold_sha256": sha256_file(gold_path),
        "questions": len(questions),
        "reviewed_questions": sum(q.reviewed for q in questions),
        "questions_with_gold_passages": sum(bool(q.gold_passages) for q in questions),
        "provisional": not all(q.reviewed for q in questions),
        "embedding_model": (
            {
                "model_id": embedder.model_id,
                "revision": embedder.model_revision,
                "dimension": embedder.dimension,
                "max_input_tokens": embedder.max_input_tokens,
            }
            if embedder
            else None
        ),
        # The implementation actually used, not the configured name (tests inject fakes).
        "reranker_model": (
            {
                "model_id": reranker.model_id,
                "revision": reranker.model_revision,
                "max_input_tokens": reranker.max_input_tokens,
            }
            if reranker
            else None
        ),
        "embedding_template_version": TEMPLATE_VERSION,
        "settings": {name: getattr(settings, name) for name in RANKING_SETTINGS},
        "corpus": corpus,
    }


def store_run(
    engine: Engine,
    config: dict[str, Any],
    metrics: dict[str, Any],
    per_question: list[dict[str, Any]],
    run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    run_id = run_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(RUNS).values(
                id=run_id,
                config=json.loads(json.dumps(config)),
                metrics=metrics,
                per_question=per_question,
            )
        )
    return run_id

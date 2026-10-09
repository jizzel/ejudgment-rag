"""Answer evaluation against ``evals/gold.jsonl`` (M3).

Every gold question goes through the same path as ``/v1/chat``. Reported (all provisional
while the questions are ``reviewed=false``):

- ``answered_rate``: answerable questions that got an answer (not an abstention);
- ``gold_cited_rate``: answerable questions whose answer cites a gold case;
- ``evidence_precision``: share of cited cases that are gold cases (answered questions);
- ``no_answer_abstention_rate``: ``expect_no_answer`` questions that abstained;
- ``citation_id_validity``: source ids cited by the model that exist in its context;
- ``quote_support_rate``: model claims that survived verification (quote, references and
  NLI entailment);
- latency (whole request, model load included on the first) and tokens.
"""

import statistics
import time
import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import Engine

from ejudgment.config import Settings
from ejudgment.domain.schemas import ChatRequest, ChatResponse
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.evaluation.retrieval import GoldQuestion, percentile
from ejudgment.generation.base import LLMProvider
from ejudgment.generation.budget import BudgetExhausted
from ejudgment.generation.chat import AnswerTrace, answer_question
from ejudgment.generation.prompt import PROMPT_VERSION
from ejudgment.verification.entailment import EntailmentModel
from ejudgment.verification.support import SUPPORT_VERSION

ENDPOINT = "evaluate_answers"

# Every setting that can change a generated answer; a run records their values.
GENERATION_SETTINGS = (
    "llm_provider",
    "ollama_chat_model",
    "ollama_num_ctx",
    "llm_max_output_tokens",
    "generation_max_passages",
    "generation_passages_per_case",
    "generation_max_context_tokens",
    "generation_case_closing_passages",
    "generation_max_claims",
    "generation_min_quote_words",
    "nli_model_id",
    "nli_revision",
    "nli_max_input_tokens",
    "nli_min_entailment",
    "openai_chat_model",
    "openai_reasoning_effort",
    "openai_max_output_tokens",
    "openai_max_input_tokens",
    "openai_max_calls_per_run",
    "openai_test_budget_usd",
    "openai_prices",
)


def _cited_uris(response: ChatResponse) -> list[set[str]]:
    return [
        {source.judgment.canonical_uri} | {ref.canonical_uri for ref in source.also_published_as}
        for source in response.sources
    ]


def _record(
    question: GoldQuestion, response: ChatResponse, trace: AnswerTrace, latency_ms: float
) -> dict[str, Any]:
    """Metrics inputs plus the evidence to review the answer later without re-running it:
    the answer and its claims (quotes, chunk ids, support scores), the passages sent,
    the model's raw structured output and every removed claim."""
    generation = response.generation
    gold = set(question.gold_canonical_uris)
    cited = _cited_uris(response)
    removed = generation.removed_claims if generation else {}
    return {
        "id": question.id,
        "category": question.category,
        "expect_no_answer": question.expect_no_answer,
        "abstained": response.abstained,
        "abstain_reason": response.abstain_reason,
        "claims": len(response.claims),
        "removed_claims": removed,
        "source_ids_cited": generation.source_ids_cited if generation else 0,
        "invalid_source_ids": generation.invalid_source_ids if generation else 0,
        "cited_cases": len(cited),
        "gold_cases_cited": sum(1 for uris in cited if uris & gold),
        "cited": [source.judgment.canonical_uri for source in response.sources],
        "matched": [ref.canonical_uri for ref in response.matched_cases],
        "model": generation.model if generation else None,
        "requested_model": generation.requested_model if generation else None,
        "input_tokens": generation.input_tokens if generation else 0,
        "output_tokens": generation.output_tokens if generation else 0,
        "latency_ms": round(latency_ms, 1),
        "answer": response.answer,
        "claims_detail": [claim.model_dump(mode="json") for claim in response.claims],
        "sources_detail": [
            {
                "number": source.number,
                "canonical_uri": source.judgment.canonical_uri,
                "chunk_ids": [str(p.chunk_id) for p in source.passages],
            }
            for source in response.sources
        ],
        "removed_detail": trace.removed,
        "context": trace.context,
        "model_output": trace.model_output,
        "model_limitations": response.model_limitations,
    }


def _rate(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in records if not r["expect_no_answer"]]
    no_answer = [r for r in records if r["expect_no_answer"]]
    answered = [r for r in answerable if not r["abstained"]]
    kept = sum(r["claims"] for r in records)
    removed = sum(sum(r["removed_claims"].values()) for r in records)
    labels = sum(r["source_ids_cited"] for r in records)
    invalid = sum(r["invalid_source_ids"] for r in records)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in answerable:
        by_category[record["category"]].append(record)
    latencies = [r["latency_ms"] for r in records]
    return {
        "questions": len(records),
        "answerable": len(answerable),
        "answered_rate": _rate(len(answered), len(answerable)),
        "gold_cited_rate": _rate(
            sum(r["gold_cases_cited"] > 0 for r in answerable), len(answerable)
        ),
        "evidence_precision": _rate(
            sum(r["gold_cases_cited"] for r in answered), sum(r["cited_cases"] for r in answered)
        ),
        "no_answer_abstention_rate": _rate(sum(r["abstained"] for r in no_answer), len(no_answer)),
        "citation_id_validity": _rate(labels - invalid, labels),
        "quote_support_rate": _rate(kept, kept + removed),
        "claims_kept": kept,
        "claims_removed": dict(
            sum((Counter(r["removed_claims"]) for r in records), Counter[str]())
        ),
        "abstain_reasons": dict(Counter(r["abstain_reason"] for r in records if r["abstained"])),
        "by_category": {
            category: {
                "answered_rate": _rate(sum(not r["abstained"] for r in rows), len(rows)),
                "gold_cited_rate": _rate(sum(r["gold_cases_cited"] > 0 for r in rows), len(rows)),
            }
            for category, rows in sorted(by_category.items())
        },
        "latency_p50_ms": round(percentile(latencies, 0.5), 1) if latencies else None,
        "latency_p95_ms": round(percentile(latencies, 0.95), 1) if latencies else None,
        "mean_input_tokens": round(statistics.fmean(r["input_tokens"] for r in records), 1)
        if records
        else None,
        "mean_output_tokens": round(statistics.fmean(r["output_tokens"] for r in records), 1)
        if records
        else None,
    }


async def evaluate_answers(
    engine: Engine,
    settings: Settings,
    questions: list[GoldQuestion],
    *,
    embedder: EmbeddingProvider | None,
    reranker: Reranker | None,
    llm: LLMProvider,
    nli: EntailmentModel,
    run_id: uuid.UUID,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Ledger rows of the run carry ``run_id``. Model unavailability aborts the run."""
    records: list[dict[str, Any]] = []
    stopped: BudgetExhausted | None = None
    for question in questions:
        request = ChatRequest(question=question.question, filters=question.filters)
        started = time.perf_counter()
        trace = AnswerTrace()
        try:
            response = await answer_question(
                engine,
                request,
                settings,
                embedder=embedder,
                reranker=reranker,
                llm=llm,
                nli=nli,
                endpoint=ENDPOINT,
                run_id=run_id,
                trace=trace,
            )
        except BudgetExhausted as exc:
            stopped = exc  # the soft stop: no further calls in this run
            break
        records.append(_record(question, response, trace, (time.perf_counter() - started) * 1000))
    metrics = summarise(records)
    if stopped is not None:
        metrics["budget_stopped"] = {"reason": stopped.reason, "message": str(stopped)}
        metrics["not_run"] = [q.id for q in questions[len(records) :]]
    return metrics, records


def generation_config(
    settings: Settings,
    llm: LLMProvider,
    nli: EntailmentModel,
    described: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": "answers",
        "llm": described or {"provider": llm.provider, "model": llm.model},
        # What the provider reported running; differs from "llm" when the name is an alias.
        "models_reported": sorted({r["model"] for r in records if r.get("model")}),
        "support_model": {"model_id": nli.model_id, "revision": nli.model_revision},
        "support_version": SUPPORT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "generation_settings": settings.model_dump(mode="json", include=set(GENERATION_SETTINGS)),
    }

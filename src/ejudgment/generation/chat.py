"""Grounded answers: retrieve, generate with source labels, verify, and build the answer.

The answer text is assembled server-side from verified claims only; citations, links and
page references come from the database, never from model text. Every model call is
recorded in ``llm_usage_ledger`` (no text), every question in ``query_audit`` (hashed).
"""

import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

import anyio
from pydantic import ValidationError
from sqlalchemy import Engine, Table, insert

from ejudgment.config import Settings
from ejudgment.domain.enums import LlmCallStatus
from ejudgment.domain.models import LlmUsage
from ejudgment.domain.schemas import (
    AbstainReason,
    ChatClaim,
    ChatPassage,
    ChatProgressEvent,
    ChatRequest,
    ChatResponse,
    ChatSource,
    ChatSourcesEvent,
    ChatStageEvent,
    GenerationInfo,
    JudgmentRef,
    PassageResult,
    SearchRequest,
    SearchResponse,
)
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.generation.base import LLMOutputError, LLMProvider, LLMUnavailable, TokenUsage
from ejudgment.generation.budget import (
    PRICED_PROVIDERS,
    BudgetExhausted,
    check_budget,
    estimate_request_tokens,
    estimate_usd,
    model_price,
    select_sources,
    worst_case_usd,
)
from ejudgment.generation.prompt import (
    PROMPT_VERSION,
    LabelledSource,
    ModelAnswer,
    build_messages,
    response_schema,
)
from ejudgment.ingestion.hashing import sha256_text
from ejudgment.retrieval.service import closing_passages, record_audit, search
from ejudgment.verification.citations import eligible_chunk_ids
from ejudgment.verification.entailment import EntailmentModel
from ejudgment.verification.support import Verification, check_support, verify_answer

LEDGER = cast(Table, LlmUsage.__table__)


@dataclass
class AnswerTrace:
    """Evaluation evidence the API response omits (never shown to users)."""

    context: list[dict[str, str]] = field(default_factory=list)
    model_output: dict[str, Any] | str | None = None
    removed: list[dict[str, Any]] = field(default_factory=list)


Progress = Callable[[ChatProgressEvent], Awaitable[None]]


@dataclass
class _CallState:
    """What a cancelled answer must still record (see :func:`answer_question`)."""

    started: float
    matched_ids: list[uuid.UUID] = field(default_factory=list)
    recorded: bool = False
    llm_started: float | None = None
    request_tokens: int = 0
    max_output_tokens: int = 0


MATCHED_CASES = 5
_EXACT_MATCHES = ("citation", "case_name")


def _retrieve(
    engine: Engine,
    request: ChatRequest,
    settings: Settings,
    embedder: EmbeddingProvider | None,
    reranker: Reranker | None,
) -> tuple[SearchResponse, list[LabelledSource]]:
    search_request = SearchRequest(
        query=request.question,
        filters=request.filters,
        # Never deeper than search allows (search_max_depth is configured separately).
        top_k=min(settings.generation_max_passages, settings.search_max_depth),
        mode="hybrid",
        rerank=True,
    )
    with engine.connect() as conn:
        response = search(conn, search_request, settings, embedder=embedder, reranker=reranker)
        closing: list[PassageResult] = []
        top = response.cases[0] if response.cases else None
        if top is not None and top.match_type in _EXACT_MATCHES:
            closing = closing_passages(
                conn, top, settings.generation_case_closing_passages, settings
            )
        sources = select_sources(response, settings, closing)
        # Defence in depth: retrieval is eligible-only, but re-check before generation.
        eligible = eligible_chunk_ids(conn, [s.passage.chunk_id for s in sources])
    kept = [source for source in sources if source.passage.chunk_id in eligible]
    return response, [LabelledSource(f"S{i}", s.passage) for i, s in enumerate(kept, 1)]


def _pinpoint(passage: PassageResult) -> str | None:
    if passage.page_reference_status != "verified" or passage.page_start is None:
        return None
    first, last = passage.page_start + 1, (passage.page_end or passage.page_start) + 1
    return f"PDF page {first}" if first == last else f"PDF pages {first}-{last}"


def _render(
    verification: Verification, response: SearchResponse
) -> tuple[str, list[ChatClaim], list[ChatSource]]:
    twins = {case.judgment.judgment_id: case.also_published_as for case in response.cases}
    numbers: dict[uuid.UUID, int] = {}
    sources: list[ChatSource] = []
    claims: list[ChatClaim] = []
    for claim in verification.kept:
        claim_numbers: list[int] = []
        for cited in claim.sources:
            judgment = cited.passage.judgment
            if judgment.judgment_id not in numbers:
                numbers[judgment.judgment_id] = len(sources) + 1
                sources.append(
                    ChatSource(
                        number=len(sources) + 1,
                        judgment=judgment,
                        also_published_as=twins.get(judgment.judgment_id, []),
                        passages=[],
                    )
                )
            source = sources[numbers[judgment.judgment_id] - 1]
            if all(p.chunk_id != cited.passage.chunk_id for p in source.passages):
                source.passages.append(
                    ChatPassage(
                        chunk_id=cited.passage.chunk_id,
                        excerpt=cited.passage.excerpt,
                        page_reference_status=cited.passage.page_reference_status,
                        page_start=cited.passage.page_start,
                        page_end=cited.passage.page_end,
                    )
                )
            if numbers[judgment.judgment_id] not in claim_numbers:
                claim_numbers.append(numbers[judgment.judgment_id])
        claims.append(
            ChatClaim(
                text=claim.text,
                kind=claim.kind,
                source_numbers=claim_numbers,
                quote=claim.quote,
                quote_chunk_id=claim.quote_source.passage.chunk_id,
                pinpoint=_pinpoint(claim.quote_source.passage),
                support_score=claim.support_score,
            )
        )
    answer = "\n".join(
        f"{claim.text} {''.join(f'[{n}]' for n in claim.source_numbers)}" for claim in claims
    )
    return answer, claims, sources


def _limitations(
    response: SearchResponse, verification: Verification | None, sources: list[ChatSource]
) -> list[str]:
    notes: list[str] = []
    if response.query_info.degraded:
        notes.append(f"Retrieval was degraded: {response.query_info.degraded_reason}.")
    if verification is not None and verification.removed:
        notes.append(
            f"{len(verification.removed)} statement(s) generated by the model were removed "
            "because the cited passages did not support them."
        )
    unpaged = [
        p for source in sources for p in source.passages if p.page_reference_status != "verified"
    ]
    if unpaged:
        notes.append(
            "Some cited passages have no verified page numbers; cite them by case and link only."
        )
    return notes


def _ledger_row(
    llm: LLMProvider,
    usage: TokenUsage | None,
    started: float,
    settings: Settings,
    *,
    endpoint: str,
    run_id: uuid.UUID | None,
    error_code: str | None,
    reported_model: str | None = None,
) -> dict[str, Any]:
    """The ledger records the model the provider reports; the price is looked up by the
    configured (requested) name, which is what ``openai_prices`` lists."""
    return {
        "id": uuid.uuid4(),
        "run_id": run_id,
        "endpoint": endpoint,
        "provider": llm.provider,
        "model": reported_model or llm.model,
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "cached_input_tokens": usage.cached_input_tokens if usage else 0,
        "estimated_usd": estimate_usd(model_price(settings, llm.provider, llm.model), usage),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "status": (LlmCallStatus.ERROR if error_code else LlmCallStatus.OK).value,
        "error_code": error_code,
    }


def _record(
    engine: Engine,
    request: ChatRequest,
    settings: Settings,
    started: float,
    endpoint: str,
    judgment_ids: list[uuid.UUID],
    ledger: dict[str, Any] | None,
    user_id: uuid.UUID | None = None,
) -> None:
    with engine.begin() as conn:
        if ledger is not None:
            conn.execute(insert(LEDGER).values(**ledger))
        record_audit(
            conn,
            request.question,
            request.filters,
            judgment_ids,
            started,
            settings,
            endpoint,
            user_id=user_id,
        )


async def answer_question(
    engine: Engine,
    request: ChatRequest,
    settings: Settings,
    *,
    embedder: EmbeddingProvider | None,
    reranker: Reranker | None,
    llm: LLMProvider,
    nli: EntailmentModel,
    endpoint: str = "/v1/chat",
    run_id: uuid.UUID | None = None,
    trace: AnswerTrace | None = None,
    user_id: uuid.UUID | None = None,
    progress: Progress | None = None,
) -> ChatResponse:
    """Raises :class:`LLMUnavailable` when the model cannot be reached (after recording it),
    and :class:`BudgetExhausted` when a priced call would break the run's limits (no call).

    ``trace`` (evaluation only) is filled with what the response leaves out: the passages
    sent, the model's raw structured output and every removed claim with its reason.

    ``progress`` (the streaming API) receives each stage as it starts and the passages sent to
    the model. If the caller is cancelled (the reader went away), the question is still
    audited and a started model call is recorded as ``cancelled``; for a priced provider at
    its worst-case cost, since the provider may bill it anyway.
    """
    state = _CallState(started=time.perf_counter())
    try:
        return await _answer_question(
            engine,
            request,
            settings,
            embedder=embedder,
            reranker=reranker,
            llm=llm,
            nli=nli,
            endpoint=endpoint,
            run_id=run_id,
            trace=trace if trace is not None else AnswerTrace(),
            user_id=user_id,
            progress=progress,
            state=state,
        )
    except anyio.get_cancelled_exc_class():
        if not state.recorded:
            ledger = None
            if state.llm_started is not None:
                ledger = _ledger_row(
                    llm,
                    None,
                    state.llm_started,
                    settings,
                    endpoint=endpoint,
                    run_id=run_id,
                    error_code="cancelled",
                )
                price = model_price(settings, llm.provider, llm.model)
                if price is not None:
                    worst = worst_case_usd(price, state.request_tokens, state.max_output_tokens)
                    ledger["estimated_usd"] = Decimal(str(round(worst, 6)))
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(
                    _record,
                    engine,
                    request,
                    settings,
                    state.started,
                    endpoint,
                    state.matched_ids,
                    ledger,
                    user_id,
                )
        raise


async def _answer_question(
    engine: Engine,
    request: ChatRequest,
    settings: Settings,
    *,
    embedder: EmbeddingProvider | None,
    reranker: Reranker | None,
    llm: LLMProvider,
    nli: EntailmentModel,
    endpoint: str,
    run_id: uuid.UUID | None,
    trace: AnswerTrace,
    user_id: uuid.UUID | None,
    progress: Progress | None,
    state: _CallState,
) -> ChatResponse:
    async def emit(event: ChatProgressEvent) -> None:
        if progress is not None:
            await progress(event)

    started = state.started
    await emit(ChatStageEvent(stage="searching"))
    response, sources = await anyio.to_thread.run_sync(
        _retrieve, engine, request, settings, embedder, reranker
    )
    trace.context = [
        {
            "label": source.label,
            "chunk_id": str(source.passage.chunk_id),
            "canonical_uri": source.passage.judgment.canonical_uri,
            "excerpt_sha256": sha256_text(source.passage.excerpt),
        }
        for source in sources
    ]
    matched: list[JudgmentRef] = [case.judgment for case in response.cases[:MATCHED_CASES]]
    matched_ids = [ref.judgment_id for ref in matched]
    state.matched_ids = matched_ids
    if sources:
        await emit(ChatSourcesEvent(passages=[source.passage for source in sources]))

    def abstain(
        reason: AbstainReason,
        generation: GenerationInfo | None = None,
        model_limitations: str | None = None,
    ) -> ChatResponse:
        return ChatResponse(
            question=request.question,
            session_id=request.session_id,
            abstained=True,
            abstain_reason=reason,
            answer=None,
            claims=[],
            sources=[],
            limitations=_limitations(response, None, []),
            model_limitations=model_limitations or None,
            matched_cases=matched,
            query_info=response.query_info,
            generation=generation,
        )

    if not sources:
        await anyio.to_thread.run_sync(
            _record, engine, request, settings, started, endpoint, matched_ids, None, user_id
        )
        state.recorded = True
        return abstain("no_results")

    max_claims = settings.generation_max_claims
    messages = build_messages(
        request.question,
        sources,
        min_quote_words=settings.generation_min_quote_words,
        max_claims=max_claims,
    )
    max_output_tokens = (
        settings.openai_max_output_tokens
        if llm.provider in PRICED_PROVIDERS
        else settings.llm_max_output_tokens
    )

    schema = response_schema(max_claims)

    def guard() -> None:
        with engine.connect() as conn:
            check_budget(
                conn,
                settings,
                provider=llm.provider,
                model=llm.model,
                messages=messages,
                response_schema=schema,
                max_output_tokens=max_output_tokens,
                run_id=run_id,
                endpoint=endpoint,
            )

    try:
        await anyio.to_thread.run_sync(guard)
    except BudgetExhausted:
        # No model call is made; the question itself is still audited.
        await anyio.to_thread.run_sync(
            _record, engine, request, settings, started, endpoint, matched_ids, None, user_id
        )
        state.recorded = True
        raise

    await emit(ChatStageEvent(stage="drafting"))
    llm_started = time.perf_counter()
    state.llm_started = llm_started
    state.request_tokens = estimate_request_tokens(messages, schema)
    state.max_output_tokens = max_output_tokens
    # The model the provider says it ran (an alias may resolve to a dated snapshot).
    reported_model: str | None = None
    usage: TokenUsage | None = None
    answer: ModelAnswer | None = None
    error_code: str | None = None
    try:
        result = await llm.generate(
            messages,
            response_schema=schema,
            max_output_tokens=max_output_tokens,
        )
        usage = result.usage
        reported_model = result.model
        trace.model_output = result.parsed if result.parsed is not None else result.text
        answer = ModelAnswer.model_validate(result.parsed or {})
    except LLMUnavailable:
        ledger = _ledger_row(
            llm,
            None,
            llm_started,
            settings,
            endpoint=endpoint,
            run_id=run_id,
            error_code="llm_unavailable",
        )
        await anyio.to_thread.run_sync(
            _record, engine, request, settings, started, endpoint, matched_ids, ledger, user_id
        )
        state.recorded = True
        raise
    except LLMOutputError as exc:
        usage, error_code = exc.usage, "invalid_model_output"
        trace.model_output = f"invalid output: {exc}"
    except ValidationError:
        error_code = "invalid_model_output"
    ledger = _ledger_row(
        llm,
        usage,
        llm_started,
        settings,
        endpoint=endpoint,
        run_id=run_id,
        error_code=error_code,
        reported_model=reported_model,
    )
    # Record the model call before verification, which can fail on its own (NLI runtime).
    await anyio.to_thread.run_sync(
        _record, engine, request, settings, started, endpoint, matched_ids, ledger, user_id
    )
    state.recorded = True

    verification: Verification | None = None
    if answer is not None and not answer.abstain:
        quoted = verify_answer(
            answer,
            sources,
            min_quote_words=settings.generation_min_quote_words,
            max_claims=max_claims,
        )
        await emit(ChatStageEvent(stage="checking", claims=len(answer.claims)))
        verification = await anyio.to_thread.run_sync(
            lambda: check_support(quoted, nli, min_entailment=settings.nli_min_entailment)
        )
        trace.removed = [
            {
                "text": claim.text,
                "reason": claim.reason,
                "sources": claim.sources,
                "quote": claim.quote,
                "support_score": claim.support_score,
            }
            for claim in verification.removed
        ]
    generation = GenerationInfo(
        provider=llm.provider,
        model=reported_model or llm.model,
        requested_model=llm.model,
        prompt_version=PROMPT_VERSION,
        support_model=f"{nli.model_id}@{nli.model_revision}",
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        latency_ms=ledger["latency_ms"],
        sources_sent=len(sources),
        source_ids_cited=verification.labels_cited if verification else 0,
        invalid_source_ids=len(verification.invalid_labels) if verification else 0,
        removed_claims=dict(Counter(c.reason for c in verification.removed))
        if verification
        else {},
    )
    model_limitations = answer.limitations.strip() if answer is not None else None
    if answer is None:
        return abstain("invalid_model_output", generation)
    if answer.abstain:
        return abstain("model_abstained", generation, model_limitations)
    assert verification is not None
    if not verification.kept:
        result_ = abstain("no_supported_claims", generation, model_limitations)
        result_.limitations = _limitations(response, verification, [])
        return result_
    text, claims, cited = _render(verification, response)
    return ChatResponse(
        question=request.question,
        session_id=request.session_id,
        abstained=False,
        abstain_reason=None,
        answer=text,
        claims=claims,
        sources=cited,
        limitations=_limitations(response, verification, cited),
        model_limitations=model_limitations or None,
        matched_cases=matched,
        query_info=response.query_info,
        generation=generation,
    )

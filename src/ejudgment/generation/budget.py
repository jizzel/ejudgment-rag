"""Budgets: the passages sent to the model (context), and the cost of priced model calls.

Context: choose the passages sent to the model, within a token budget.

Passages are taken case by case in retrieval order (at most ``generation_passages_per_case``
each, ``generation_max_passages`` in total). When the question names a case (exact citation
or case-name match ranked first), that case's closing passages are added, since its leading
chunk usually holds only the parties and the bench. Token counts are estimates (the LLM's
tokenizer differs from the embedding model's), so the budget keeps a margin.
"""

import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ejudgment.config import ModelPrice, Settings
from ejudgment.domain.schemas import PassageResult, SearchResponse
from ejudgment.generation.base import TokenUsage
from ejudgment.generation.prompt import LabelledSource

_CHARS_PER_TOKEN = 3.5
_ENVELOPE_TOKENS = 40


def estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + _ENVELOPE_TOKENS


def _candidates(
    response: SearchResponse, settings: Settings, closing: list[PassageResult]
) -> Iterable[PassageResult]:
    for index, case in enumerate(response.cases):
        passages = case.passages[: settings.generation_passages_per_case]
        if index == 0 and closing:
            yield from passages[:1]
            yield from closing
            continue
        yield from passages


def select_sources(
    response: SearchResponse, settings: Settings, closing: list[PassageResult] | None = None
) -> list[LabelledSource]:
    chosen: list[PassageResult] = []
    seen: set[object] = set()
    used = 0
    for passage in _candidates(response, settings, closing or []):
        if len(chosen) >= settings.generation_max_passages:
            break
        if passage.chunk_id in seen:
            continue
        cost = estimate_tokens(passage.excerpt)
        if used + cost > settings.generation_max_context_tokens:
            continue  # a shorter later passage may still fit
        chosen.append(passage)
        seen.add(passage.chunk_id)
        used += cost
    return [LabelledSource(f"S{i}", passage) for i, passage in enumerate(chosen, 1)]


# --- Cost and the per-run soft stop for priced providers (OpenAI) ----------------------------

PRICED_PROVIDERS = frozenset({"openai"})


class BudgetExhausted(Exception):
    """A priced call would exceed the run's call or USD limit, or the input token cap."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason  # max_calls | budget | input_too_large


class UnpricedModel(ValueError):
    """A priced provider's model has no entry in ``openai_prices``."""


def model_price(settings: Settings, provider: str, model: str) -> ModelPrice | None:
    """The price of a priced provider's model; ``None`` for free local providers."""
    if provider not in PRICED_PROVIDERS:
        return None
    price = settings.openai_prices.get(model)
    if price is None:
        raise UnpricedModel(f"no price configured for {provider} model {model!r}")
    return price


def estimate_usd(price: ModelPrice | None, usage: TokenUsage | None) -> Decimal:
    """Estimated cost of one call from its reported usage (cached input billed separately)."""
    if price is None or usage is None:
        return Decimal(0)
    uncached = max(usage.input_tokens - usage.cached_input_tokens, 0)
    usd = (
        uncached * price.input
        + usage.cached_input_tokens * price.cached_input
        + usage.output_tokens * price.output
    ) / 1_000_000
    return Decimal(str(round(usd, 6)))


def estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    return sum(estimate_tokens(message["content"]) for message in messages)


def worst_case_usd(price: ModelPrice, input_tokens: int, max_output_tokens: int) -> float:
    """Upper estimate before the call: every input token uncached, the full output used."""
    return (input_tokens * price.input + max_output_tokens * price.output) / 1_000_000


def check_budget(
    conn: Connection,
    settings: Settings,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    max_output_tokens: int,
    run_id: uuid.UUID | None,
    endpoint: str,
) -> None:
    """Raise :class:`BudgetExhausted` before a priced call that would break the limits.

    The run is an evaluation/pilot ``run_id``; calls without one (the API) share one run per
    endpoint, provider and UTC day. This is an application-side soft stop read from
    ``llm_usage_ledger``: concurrent requests can overshoot it slightly, and it is no
    substitute for a budget set on the provider's platform.
    """
    price = model_price(settings, provider, model)
    if price is None:
        return
    input_tokens = estimate_message_tokens(messages)
    if input_tokens > settings.openai_max_input_tokens:
        raise BudgetExhausted(
            f"prompt of ~{input_tokens} tokens exceeds openai_max_input_tokens "
            f"({settings.openai_max_input_tokens})",
            reason="input_too_large",
        )
    if run_id is not None:
        scope = "run_id = :run_id"
        params: dict[str, Any] = {"run_id": run_id}
    else:
        scope = (
            "run_id IS NULL AND endpoint = :endpoint AND provider = :provider "
            "AND created_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        )
        params = {"endpoint": endpoint, "provider": provider}
    row = conn.execute(
        text(
            "SELECT count(*) AS calls, coalesce(sum(estimated_usd), 0) AS spent "
            f"FROM llm_usage_ledger WHERE {scope}"
        ),
        params,
    ).one()
    if row.calls >= settings.openai_max_calls_per_run:
        raise BudgetExhausted(
            f"{row.calls} calls already made in this run (limit "
            f"{settings.openai_max_calls_per_run})",
            reason="max_calls",
        )
    next_call = worst_case_usd(price, input_tokens, max_output_tokens)
    if float(row.spent) + next_call > settings.openai_test_budget_usd:
        raise BudgetExhausted(
            f"run spent ${float(row.spent):.4f}; the next call (up to ${next_call:.4f}) would "
            f"exceed the ${settings.openai_test_budget_usd:.2f} budget",
            reason="budget",
        )

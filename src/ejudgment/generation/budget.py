"""Choose the passages sent to the model, within a context budget.

Passages are taken case by case in retrieval order (at most ``generation_passages_per_case``
each, ``generation_max_passages`` in total). When the question names a case (exact citation
or case-name match ranked first), that case's closing passages are added, since its leading
chunk usually holds only the parties and the bench. Token counts are estimates (the LLM's
tokenizer differs from the embedding model's), so the budget keeps a margin.
"""

from collections.abc import Iterable

from ejudgment.config import Settings
from ejudgment.domain.schemas import PassageResult, SearchResponse
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

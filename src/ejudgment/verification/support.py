"""Claim verification: quoted evidence, no invented references, and entailment.

1. The quote must be at least ``min_quote_words`` words and occur verbatim in one of the
   claim's own cited passages, after normalising whitespace, case, typographic quotes and
   dashes. A quote may skip text with an ellipsis; its parts must then occur in order.
2. A neutral citation in the claim text must be a cited judgment's own or appear in its
   passages. Page references are never accepted in model text: pinpoints come only from
   the server's verified page mapping.
3. A quote proves the words exist, not that the claim follows from them, so the claim must
   be entailed by one of its cited passages: copied verbatim, or judged entailed by an NLI
   model on a window of 1-3 sentences (:func:`check_support`).
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace

from ejudgment.domain.schemas import ClaimKind
from ejudgment.generation.prompt import LabelledSource, ModelAnswer
from ejudgment.ingestion.normalize import parse_neutral_citation
from ejudgment.verification.citations import resolve_labels
from ejudgment.verification.entailment import EntailmentModel

_TRANSLATE = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
        "−": "-",
        "­": None,
        "​": None,
        "﻿": None,
    }
)
_ELLIPSIS = re.compile(r"\s*(?:\.\s*){3,}\s*|\s*…\s*")
_EDGE = " \t\n\"'`.,;:"
_CITATION = re.compile(r"\[\s*\d{4}\s*\]\s*[A-Za-z]+\s*\d+")
# "page 12", "pages 3-4", "p. 12", "p 12", "pp 3", "pg. 7": a dot, or else a space, before the
# number, so exhibit labels such as "Exhibit P1" are not taken for page references.
_PAGE_REF = re.compile(r"\b(?:pages?|pgs?|pp?)(?:\.\s*|\s+)\d+", re.IGNORECASE)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    return " ".join(text.split()).casefold()


def _parts(quote: str) -> list[str]:
    return [part for part in (normalise(p).strip(_EDGE) for p in _ELLIPSIS.split(quote)) if part]


def quote_in(quote: str, passage: str) -> bool:
    """All parts of the quote occur in the passage, in order."""
    haystack = normalise(passage)
    position = 0
    for part in _parts(quote):
        found = haystack.find(part, position)
        if found < 0:
            return False
        position = found + len(part)
    return True


def quote_words(quote: str) -> int:
    return sum(len(part.split()) for part in _parts(quote))


def _references_supported(claim_text: str, cited: list[LabelledSource]) -> bool:
    passages = " ".join(normalise(source.passage.excerpt) for source in cited)
    own = {parse_neutral_citation(source.passage.judgment.citation) for source in cited} - {None}
    for match in _CITATION.finditer(claim_text):
        if parse_neutral_citation(match.group(0)) in own:
            continue
        if normalise(match.group(0)) not in passages:
            return False
    return _PAGE_REF.search(claim_text) is None


@dataclass(frozen=True)
class SupportedClaim:
    text: str
    kind: ClaimKind
    sources: list[LabelledSource]
    quote: str
    quote_source: LabelledSource
    support_score: float | None = None  # NLI entailment probability, once checked


@dataclass(frozen=True)
class RemovedClaim:
    text: str
    # no_valid_source | quote_too_short | quote_not_found | unsupported_reference
    # | not_entailed | contradicted
    reason: str
    sources: list[str] = field(default_factory=list)
    quote: str = ""
    support_score: float | None = None


@dataclass
class Verification:
    kept: list[SupportedClaim] = field(default_factory=list)
    removed: list[RemovedClaim] = field(default_factory=list)
    labels_cited: int = 0
    invalid_labels: list[str] = field(default_factory=list)


def verify_answer(
    answer: ModelAnswer,
    sources: list[LabelledSource],
    *,
    min_quote_words: int,
    max_claims: int,
) -> Verification:
    by_label = {source.label: source for source in sources}
    result = Verification()
    for claim in answer.claims[:max_claims]:
        cited, invalid = resolve_labels(claim.sources, by_label)
        result.labels_cited += len(claim.sources)
        result.invalid_labels.extend(invalid)
        reason: str | None = None
        quoted: LabelledSource | None = None
        if not cited:
            reason = "no_valid_source"
        elif quote_words(claim.quote) < min_quote_words:
            reason = "quote_too_short"
        else:
            quoted = next((s for s in cited if quote_in(claim.quote, s.passage.excerpt)), None)
            if quoted is None:
                reason = "quote_not_found"
            elif not _references_supported(claim.text, cited):
                reason = "unsupported_reference"
        if reason is not None or quoted is None:
            result.removed.append(
                RemovedClaim(claim.text, reason or "quote_not_found", claim.sources, claim.quote)
            )
            continue
        result.kept.append(
            SupportedClaim(claim.text.strip(), claim.kind, cited, claim.quote.strip(), quoted)
        )
    return result


# How claims are checked; recorded with evaluation runs. Bump when the method changes.
SUPPORT_VERSION = "nli-sentences-v1"
# A break before a capital, quote or bracket (not a digit: "at p. 5", "s. 118(1)").
_SENTENCE_BREAK = re.compile(r"(?<=[.!?;])\s+(?=[A-Z\"“(\[])|\n\s*\n")
_MIN_SENTENCE_WORDS = 4
WINDOW_SENTENCES = (1, 2, 3)


def sentences(text: str) -> list[str]:
    """Rough sentence split; fragments shorter than a few words join the previous one."""
    result: list[str] = []
    for part in _SENTENCE_BREAK.split(text):
        part = " ".join(part.split()) if part else ""
        if not part:
            continue
        if result and len(result[-1].split()) < _MIN_SENTENCE_WORDS:
            result[-1] = f"{result[-1]} {part}"
        else:
            result.append(part)
    return result


def premises(source: LabelledSource) -> list[str]:
    """Windows of 1-3 consecutive sentences, each with the case context from the database.

    NLI models are trained on short premises: on a whole passage they often call a claim
    "neutral" even when one of its sentences states it word for word (measured on real
    answers: 27 of 43 claims rejected that way). Context matters too: "We allow the appeal"
    only entails "The Court of Appeal allowed the appeal" when it is known who is speaking.
    """
    judgment = source.passage.judgment
    court = f" ({judgment.court_name})" if judgment.court_name else ""
    prefix = f"In {judgment.citation}{court}, the court said: "
    parts = sentences(source.passage.excerpt)
    windows = [
        " ".join(parts[i : i + size])
        for size in WINDOW_SENTENCES
        for i in range(max(1, len(parts) - size + 1))
    ]
    return [prefix + window for window in dict.fromkeys(windows) if window]


def _verbatim(claim_text: str, sources: list[LabelledSource]) -> bool:
    """A claim that copies its passage word for word is supported by definition."""
    claim = normalise(claim_text).strip(_EDGE)
    return bool(claim) and any(claim in normalise(s.passage.excerpt) for s in sources)


def check_support(
    verification: Verification, nli: EntailmentModel, *, min_entailment: float
) -> Verification:
    """Keep a claim only if one of its cited passages entails it: verbatim, or by NLI on a
    window of 1-3 sentences (best window wins). A claim nothing entails is removed as
    ``contradicted`` when a window of its quoted passage contradicts it, else
    ``not_entailed``."""
    pairs: list[tuple[str, str]] = []
    spans: list[tuple[int, int, int]] = []  # start, end of the quoted passage's windows, end
    for claim in verification.kept:
        start = len(pairs)
        if not _verbatim(claim.text, claim.sources):
            pairs.extend((premise, claim.text) for premise in premises(claim.quote_source))
            quoted_end = len(pairs)
            for source in claim.sources:
                if source != claim.quote_source:
                    pairs.extend((premise, claim.text) for premise in premises(source))
        else:
            quoted_end = start
        spans.append((start, quoted_end, len(pairs)))
    scores = nli.score(pairs)
    checked = Verification(
        removed=list(verification.removed),
        labels_cited=verification.labels_cited,
        invalid_labels=list(verification.invalid_labels),
    )
    for claim, (start, quoted_end, end) in zip(verification.kept, spans, strict=True):
        if start == end:  # verbatim
            checked.kept.append(replace(claim, support_score=1.0))
            continue
        claim_scores = scores[start:end]
        best = max(claim_scores, key=lambda score: score.entailment)
        if best.label == "entailment" and best.entailment >= min_entailment:
            checked.kept.append(replace(claim, support_score=round(best.entailment, 4)))
            continue
        quoted = scores[start:quoted_end] or claim_scores
        worst = max(quoted, key=lambda score: score.contradiction)
        reason = "contradicted" if worst.label == "contradiction" else "not_entailed"
        checked.removed.append(
            RemovedClaim(
                claim.text,
                reason,
                [source.label for source in claim.sources],
                claim.quote,
                round(best.entailment, 4),
            )
        )
    return checked

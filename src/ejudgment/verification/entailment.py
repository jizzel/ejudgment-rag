"""Proposition support with a natural-language-inference (NLI) cross-encoder.

A quote proves only that the cited words exist; the claim text is the model's paraphrase
and may say something else (even the opposite). The NLI model scores each (passage, claim)
pair as entailment / neutral / contradiction; a claim is supported only when a passage it
cites entails it. Label names are read from the model config, never assumed by position.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ejudgment.config import Settings
from ejudgment.embeddings.base import ModelUnavailable, resolve_device


@dataclass(frozen=True)
class NliScores:
    entailment: float
    neutral: float
    contradiction: float

    @property
    def label(self) -> str:
        scores = {
            "entailment": self.entailment,
            "neutral": self.neutral,
            "contradiction": self.contradiction,
        }
        return max(scores, key=lambda name: scores[name])


class EntailmentModel(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def model_revision(self) -> str: ...
    def score(self, pairs: Sequence[tuple[str, str]]) -> list[NliScores]:
        """Probabilities for (premise, hypothesis) pairs."""
        ...


def _softmax(logits: Sequence[float]) -> list[float]:
    top = max(logits)
    exps = [math.exp(value - top) for value in logits]
    total = sum(exps)
    return [value / total for value in exps]


class CrossEncoderNli:
    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import CrossEncoder

        self.device = resolve_device(settings.model_device)
        try:
            self._model = CrossEncoder(
                settings.nli_model_id,
                revision=settings.nli_revision,
                device=self.device,
                local_files_only=True,
                max_length=settings.nli_max_input_tokens,
            )
        except OSError as exc:
            raise ModelUnavailable(
                f"{settings.nli_model_id}@{settings.nli_revision} is not cached; "
                "run: poetry run python -m ejudgment.worker.models fetch-models"
            ) from exc
        labels = {
            int(index): str(name).lower()
            for index, name in self._model.model.config.id2label.items()
        }
        if set(labels.values()) != {"entailment", "neutral", "contradiction"}:
            raise ModelUnavailable(f"{settings.nli_model_id} is not a 3-way NLI model: {labels}")
        self._labels = labels
        self._model_id = settings.nli_model_id
        self._revision = settings.nli_revision

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_revision(self) -> str:
        return self._revision

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[NliScores]:
        if not pairs:
            return []
        logits = self._model.predict(
            list(pairs), show_progress_bar=False, apply_softmax=False, convert_to_numpy=True
        )
        result = []
        for row in logits:
            probabilities = _softmax([float(value) for value in row])
            by_label = {self._labels[i]: p for i, p in enumerate(probabilities)}
            result.append(NliScores(**by_label))
        return result


_WORD = re.compile(r"[a-z0-9]+")
_NEGATIONS = frozenset({"not", "no", "never", "prohibited", "unlawful", "unlawfully", "denied"})


class FakeNli:
    """Deterministic NLI for tests: entailed when every content word of the claim occurs in
    the passage; contradicted when the claim adds a negation the passage lacks."""

    model_id = "fake/word-containment-nli"
    model_revision = "v1"

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[NliScores]:
        result = []
        for premise, hypothesis in pairs:
            have = set(_WORD.findall(premise.lower()))
            claim = set(_WORD.findall(hypothesis.lower()))
            if (claim & _NEGATIONS) - have:
                result.append(NliScores(0.02, 0.08, 0.9))
            elif {w for w in claim if len(w) > 3} <= have:
                result.append(NliScores(0.9, 0.08, 0.02))
            else:
                result.append(NliScores(0.1, 0.8, 0.1))
        return result

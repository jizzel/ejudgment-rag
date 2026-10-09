"""Deterministic, download-free LLM for tests: scripted answers, no network."""

import json
from collections.abc import Callable
from typing import Any

from ejudgment.generation.base import (
    GenerationResult,
    LLMOutputError,
    LLMUnavailable,
    TokenUsage,
)

Script = Callable[[list[dict[str, str]]], dict[str, Any] | str]


class FakeLLM:
    """Returns ``script(messages)``: a dict (sent as JSON) or a raw string."""

    provider = "fake"
    model = "fake/scripted"

    def __init__(self, script: Script, *, available: bool = True) -> None:
        self._script = script
        self._available = available
        self.calls: list[list[dict[str, str]]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int,
    ) -> GenerationResult:
        if not self._available:
            raise LLMUnavailable("fake model is switched off")
        self.calls.append(messages)
        output = self._script(messages)
        text = output if isinstance(output, str) else json.dumps(output)
        usage = TokenUsage(
            input_tokens=sum(len(m["content"]) // 4 for m in messages),
            output_tokens=len(text) // 4,
        )
        parsed = output if isinstance(output, dict) else None
        if response_schema is not None and parsed is None:
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMOutputError(f"output is not JSON: {exc}", usage) from exc
            if not isinstance(value, dict):
                raise LLMOutputError("output is not a JSON object", usage)
            parsed = value
        return GenerationResult(text, parsed, usage, self.provider, self.model)

"""Generation provider interface (AGENTS.md "Provider interfaces")."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class GenerationResult:
    text: str
    parsed: dict[str, Any] | None  # validated structured output, if a schema was given
    usage: TokenUsage
    provider: str
    model: str


class LLMUnavailable(Exception):
    """The model cannot be reached or is not installed. Callers report it; never fall back."""


class LLMOutputError(Exception):
    """The model answered, but not with JSON for the requested schema."""

    def __init__(self, message: str, usage: TokenUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class LLMProvider(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int,
    ) -> GenerationResult: ...

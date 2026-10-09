"""OpenAI generation through the Responses API (opt-in; AGENTS.md "OpenAI pilot").

Structured output uses a strict JSON schema (``text.format``). Requests are not stored by
OpenAI (``store=False``). The SDK retries a failed request at most ``openai_max_retries``
times; there is no other retry loop. The API key is never logged or put in error messages.
"""

import json
from typing import Any

import httpx2
import openai
from openai import AsyncOpenAI

from ejudgment.config import Settings
from ejudgment.generation.base import (
    GenerationResult,
    LLMOutputError,
    LLMUnavailable,
    TokenUsage,
)
from ejudgment.generation.prompt import strict_schema

SCHEMA_NAME = "grounded_answer"


def _usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage(0, 0)
    details = getattr(usage, "input_tokens_details", None)
    return TokenUsage(
        input_tokens=int(usage.input_tokens or 0),
        # Reasoning tokens are billed as output and are included in output_tokens.
        output_tokens=int(usage.output_tokens or 0),
        cached_input_tokens=int(getattr(details, "cached_tokens", 0) or 0),
    )


def _refusal(response: Any) -> str | None:
    for item in response.output or []:
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                return str(getattr(content, "refusal", "") or "refused")
    return None


class OpenAIProvider:
    provider = "openai"

    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        if settings.openai_api_key is None:
            raise LLMUnavailable("OPENAI_API_KEY is not set")
        self._model = model or settings.openai_chat_model
        self._effort = settings.openai_reasoning_effort
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            http_client=http_client,
        )

    @property
    def model(self) -> str:
        return self._model

    async def describe(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self._model, "reasoning_effort": self._effort}

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int,
    ) -> GenerationResult:
        request: dict[str, Any] = {
            "model": self._model,
            "input": messages,
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": self._effort},
            "store": False,
        }
        if response_schema is not None:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "schema": strict_schema(response_schema),
                    "strict": True,
                }
            }
        try:
            response = await self._client.responses.create(**request)
        except openai.RateLimitError as exc:
            raise LLMUnavailable("OpenAI rate limit or quota exceeded (HTTP 429)") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise LLMUnavailable(
                f"OpenAI rejected the API key or project (HTTP {exc.status_code})"
            ) from exc
        except openai.APITimeoutError as exc:
            raise LLMUnavailable("OpenAI timed out") from exc
        except openai.APIConnectionError as exc:
            raise LLMUnavailable("OpenAI is not reachable") from exc
        except openai.APIStatusError as exc:
            raise LLMUnavailable(f"OpenAI error (HTTP {exc.status_code})") from exc

        usage = _usage(response)
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None) or "unknown"
            raise LLMOutputError(f"output incomplete: {reason}", usage)
        refusal = _refusal(response)
        if refusal is not None:
            raise LLMOutputError(f"model refused: {refusal[:200]}", usage)
        text = response.output_text or ""
        parsed: dict[str, Any] | None = None
        if response_schema is not None:
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMOutputError(f"output is not JSON: {exc}", usage) from exc
            if not isinstance(value, dict):
                raise LLMOutputError("output is not a JSON object", usage)
            parsed = value
        # The resolved snapshot when the configured name is an alias (provenance).
        resolved = str(getattr(response, "model", None) or self._model)
        return GenerationResult(
            text=text, parsed=parsed, usage=usage, provider=self.provider, model=resolved
        )

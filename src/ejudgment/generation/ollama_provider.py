"""Local generation through the Ollama HTTP API (``/api/chat``).

Structured output uses Ollama's ``format`` (a JSON schema). Temperature is 0 and there is
one attempt per request: invalid output is reported, never retried in a loop.
"""

import json
from typing import Any

import httpx

from ejudgment.config import Settings
from ejudgment.generation.base import (
    GenerationResult,
    LLMOutputError,
    LLMUnavailable,
    TokenUsage,
)


class OllamaProvider:
    provider = "ollama"

    def __init__(
        self,
        settings: Settings,
        *,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = model or settings.ollama_chat_model
        self._num_ctx = settings.ollama_num_ctx
        self._timeout = settings.llm_timeout_seconds
        self._transport = transport  # tests pass httpx.MockTransport

    @property
    def model(self) -> str:
        return self._model

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, transport=self._transport
        )

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.post(path, json=body)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"Ollama timed out after {self._timeout:.0f} s") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama is not reachable at {self._base_url}") from exc
        if response.status_code == 404:
            raise LLMUnavailable(f"Ollama model {self._model!r} is not installed (ollama pull)")
        if response.status_code >= 400:
            raise LLMUnavailable(f"Ollama error {response.status_code}: {response.text[:200]}")
        data: dict[str, Any] = response.json()
        return data

    async def describe(self) -> dict[str, Any]:
        """Model provenance for evaluation runs: digest, size and quantization."""
        data = await self._post("/api/show", {"model": self._model})
        details = data.get("details") or {}
        tags: dict[str, Any] = {}
        try:
            async with self._client() as client:
                listing = (await client.get("/api/tags")).json()
            tags = next((m for m in listing.get("models", []) if m["name"] == self._model), {})
        except (httpx.HTTPError, ValueError):
            pass
        return {
            "provider": self.provider,
            "model": self._model,
            "digest": tags.get("digest"),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "num_ctx": self._num_ctx,
        }

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int,
    ) -> GenerationResult:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0,
                "num_ctx": self._num_ctx,
                "num_predict": max_output_tokens,
            },
        }
        if response_schema is not None:
            body["format"] = response_schema
        data = await self._post("/api/chat", body)
        usage = TokenUsage(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
        content = str((data.get("message") or {}).get("content") or "")
        parsed: dict[str, Any] | None = None
        if response_schema is not None:
            if data.get("done_reason") == "length":
                raise LLMOutputError("output cut off at the token limit", usage)
            try:
                value = json.loads(content)
            except json.JSONDecodeError as exc:
                raise LLMOutputError(f"output is not JSON: {exc}", usage) from exc
            if not isinstance(value, dict):
                raise LLMOutputError("output is not a JSON object", usage)
            parsed = value
        return GenerationResult(
            text=content, parsed=parsed, usage=usage, provider=self.provider, model=self._model
        )

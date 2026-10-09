import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from ejudgment.config import ModelPrice, Settings
from ejudgment.generation.base import LLMOutputError, LLMUnavailable, TokenUsage
from ejudgment.generation.budget import (
    UnpricedModel,
    estimate_usd,
    model_price,
    worst_case_usd,
)
from ejudgment.generation.loading import make_llm
from ejudgment.generation.ollama_provider import OllamaProvider
from ejudgment.generation.openai_provider import OpenAIProvider, strict_schema
from ejudgment.generation.prompt import response_schema

KEY = "sk-test-SECRET-do-not-leak"
LUNA = ModelPrice(input=0.10, cached_input=0.01, output=0.50)
MESSAGES = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}]


def _settings(**values: Any) -> Settings:
    base: dict[str, Any] = {
        "openai_api_key": SecretStr(KEY),
        "openai_enabled": True,
        "openai_chat_model": "gpt-6-luna",
        "openai_max_retries": 0,
        "openai_prices": {"gpt-6-luna": LUNA},
    }
    return Settings(**(base | values))


def _response(
    text: str = '{"abstain": true, "claims": [], "limitations": ""}', **fields: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-6-luna",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200},
            "output_tokens": 120,
            "output_tokens_details": {"reasoning_tokens": 20},
            "total_tokens": 1120,
        },
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }
    return body | fields


def _provider(handler: Any, **settings: Any) -> OpenAIProvider:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return OpenAIProvider(_settings(**settings), http_client=client)


def _generate(provider: OpenAIProvider, schema: dict[str, Any] | None = None) -> Any:
    return asyncio.run(
        provider.generate(
            MESSAGES, response_schema=schema or response_schema(4), max_output_tokens=450
        )
    )


def test_request_uses_a_strict_schema_and_is_not_stored() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_response())

    result = _generate(_provider(handler, openai_reasoning_effort="low"))
    body = seen["body"]
    assert seen["url"].endswith("/responses") and seen["auth"] == f"Bearer {KEY}"
    assert body["model"] == "gpt-6-luna" and body["store"] is False
    assert body["max_output_tokens"] == 450 and body["reasoning"] == {"effort": "low"}
    assert body["input"] == MESSAGES
    fmt = body["text"]["format"]
    assert (fmt["type"], fmt["strict"]) == ("json_schema", True)
    assert fmt["schema"] == strict_schema(response_schema(4))
    assert result.parsed == {"abstain": True, "claims": [], "limitations": ""}
    assert result.usage == TokenUsage(input_tokens=1000, output_tokens=120, cached_input_tokens=200)
    assert (result.provider, result.model) == ("openai", "gpt-6-luna")


def test_strict_schema_closes_every_object() -> None:
    schema = strict_schema(response_schema(4))
    claim = schema["properties"]["claims"]["items"]
    for node in (schema, claim):
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
    assert schema["properties"]["claims"]["maxItems"] == 4
    assert claim["properties"]["kind"]["enum"] == ["holding", "obiter", "fact", "inference"]
    assert "additionalProperties" not in response_schema(4)  # the original is unchanged


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            _response(status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
            "incomplete: max_output_tokens",
        ),
        (
            _response(
                output=[
                    {
                        "type": "message",
                        "id": "msg_1",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "refusal", "refusal": "I can't help with that."}],
                    }
                ]
            ),
            "refused",
        ),
        (_response(text="not json"), "not JSON"),
    ],
)
def test_unusable_output_keeps_its_usage(body: dict[str, Any], message: str) -> None:
    provider = _provider(lambda request: httpx2.Response(200, json=body))
    with pytest.raises(LLMOutputError, match=message) as caught:
        _generate(provider)
    assert caught.value.usage is not None and caught.value.usage.input_tokens == 1000


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "rejected the API key"),
        (403, "rejected the API key"),
        (429, "rate limit"),
        (500, "HTTP 500"),
    ],
)
def test_api_errors_are_unavailable_without_leaking_the_key(status: int, message: str) -> None:
    body = {"error": {"message": f"bad key {KEY}", "type": "invalid_request_error"}}
    provider = _provider(lambda request: httpx2.Response(status, json=body))
    with pytest.raises(LLMUnavailable, match=message) as caught:
        _generate(provider)
    assert KEY not in str(caught.value)


def test_unreachable_api() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(LLMUnavailable, match="not reachable"):
        _generate(_provider(refuse))


# --- cost ----------------------------------------------------------------------------------


def test_cost_estimates() -> None:
    usage = TokenUsage(input_tokens=1000, output_tokens=120, cached_input_tokens=200)
    # 800 uncached x 0.10 + 200 cached x 0.01 + 120 x 0.50, per 1M tokens
    assert estimate_usd(LUNA, usage) == Decimal("0.000142")
    assert estimate_usd(None, usage) == Decimal(0)  # local models are free
    assert worst_case_usd(LUNA, 4000, 450) == pytest.approx(0.000625)


def test_prices_are_required_for_priced_providers() -> None:
    settings = _settings()
    assert model_price(settings, "openai", "gpt-6-luna") == LUNA
    assert model_price(settings, "ollama", "gemma4:latest") is None
    with pytest.raises(UnpricedModel):
        model_price(settings, "openai", "gpt-6-astra")


def test_repository_prices_cover_the_default_model() -> None:
    settings = Settings()
    assert settings.openai_chat_model in settings.openai_prices
    assert settings.openai_enabled is False  # opt-in only


# --- provider choice -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"openai_enabled": False}, "disabled"),
        ({"openai_api_key": None}, "OPENAI_API_KEY is not set"),
        ({"openai_chat_model": "gpt-6-astra"}, "no price configured"),
    ],
)
def test_openai_is_used_only_when_enabled_keyed_and_priced(
    overrides: dict[str, Any], message: str
) -> None:
    settings = _settings(llm_provider="openai", **overrides)
    with pytest.raises(LLMUnavailable, match=message):
        make_llm(settings)  # never falls back to Ollama


def test_provider_choice() -> None:
    assert isinstance(make_llm(_settings(llm_provider="openai")), OpenAIProvider)
    assert isinstance(make_llm(_settings(llm_provider="ollama")), OllamaProvider)
    assert isinstance(make_llm(_settings(), provider="openai"), OpenAIProvider)

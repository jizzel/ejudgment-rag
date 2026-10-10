import json
from decimal import Decimal
from typing import Any

import anyio
import pytest
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, OperationalError

from ejudgment.api.routes import chat as chat_route
from ejudgment.api.routes.chat import EventStream
from ejudgment.config import Settings
from ejudgment.domain.schemas import ChatRequest, ChatStageEvent
from ejudgment.generation import chat as chat_module
from ejudgment.generation.base import GenerationResult
from ejudgment.generation.budget import estimate_request_tokens, model_price, worst_case_usd
from ejudgment.generation.chat import answer_question
from ejudgment.generation.fake import FakeLLM
from ejudgment.generation.prompt import response_schema
from ejudgment.verification.entailment import FakeNli
from tests.integration.test_chat import NLI, _client, _priced, _rows, _spend, grounded
from tests.integration.test_chat import sources_in as _sources

pytestmark = pytest.mark.integration


def events(text: str) -> list[dict[str, Any]]:
    """Parse a text/event-stream body into its events' JSON data."""
    parsed = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        assert json.loads(lines["data"])["type"] == lines["event"]
        parsed.append(json.loads(lines["data"]))
    return parsed


def test_stream_reports_stages_sources_then_the_same_answer(
    chat_engine: Engine, settings: Settings
) -> None:
    question = {"question": "marker37x3 marker37x4"}
    llm = FakeLLM(grounded)
    with _client(chat_engine, settings, llm) as client:
        streamed = client.post("/v1/chat/stream", json=question)
        plain = client.post("/v1/chat", json=question).json()
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.headers["cache-control"] == "no-cache, no-transform"
    got = events(streamed.text)
    assert [e["type"] if e["type"] != "stage" else e["stage"] for e in got] == [
        "searching",
        "sources",
        "drafting",
        "checking",
        "answer",
    ]
    # The passages shown while the model works are the ones it was sent, in that order.
    sent_first = llm.calls[0][-1]["content"]
    order = [p["excerpt"][:40] for p in got[1]["passages"]]
    assert order and [sent_first.index(x) for x in order] == sorted(
        sent_first.index(x) for x in order
    )
    assert got[3]["claims"] == len(grounded(llm.calls[0])["claims"])
    answer, same = got[-1]["answer"], plain
    assert {k: v for k, v in answer.items() if k != "generation"} == {
        k: v for k, v in same.items() if k != "generation"
    }
    # Both routes share the chat budget and audit name.
    assert len(_rows(chat_engine, "SELECT * FROM query_audit WHERE endpoint = '/v1/chat'")) == 2


def test_stream_without_results_skips_the_model(chat_engine: Engine, settings: Settings) -> None:
    llm = FakeLLM(grounded)
    with _client(chat_engine, settings, llm) as client:
        got = events(client.post("/v1/chat/stream", json={"question": "zzqxv flurbington"}).text)
    assert [e["type"] for e in got] == ["stage", "answer"]
    assert got[-1]["answer"]["abstain_reason"] == "no_results" and llm.calls == []


def test_stream_errors(chat_engine: Engine, settings: Settings) -> None:
    question = {"question": "marker37x3"}
    with _client(chat_engine, settings, FakeLLM(grounded, available=False)) as client:
        got = events(client.post("/v1/chat/stream", json=question).text)
    assert got[-1] == {
        "type": "error",
        "error": {
            "code": "llm_unavailable",
            "message": "fake model is switched off",
            "details": None,
        },
    }
    assert [
        tuple(r) for r in _rows(chat_engine, "SELECT status, error_code FROM llm_usage_ledger")
    ] == [("error", "llm_unavailable")]
    # Refused before the stream starts: plain HTTP errors, as on /v1/chat.
    with _client(chat_engine, settings, None) as client:
        assert (
            client.post("/v1/chat/stream", json=question).json()["error"]["code"]
            == "llm_unavailable"
        )
    with _client(chat_engine, settings, FakeLLM(grounded), nli=None) as client:
        response = client.post("/v1/chat/stream", json=question)
        assert (response.status_code, response.json()["error"]["code"]) == (
            503,
            "verifier_unavailable",
        )
        assert client.post("/v1/chat/stream", json={"question": "  "}).status_code == 422


def test_stream_budget_stop_is_an_error_event(chat_engine: Engine, settings: Settings) -> None:
    from tests.integration.test_chat import PricedLLM

    priced = _priced(settings, openai_test_budget_usd=0.0001)
    _spend(chat_engine, "0.0001")
    llm = PricedLLM(grounded)
    with _client(chat_engine, priced, llm) as client:
        got = events(client.post("/v1/chat/stream", json={"question": "marker37x3"}).text)
    assert got[-1]["type"] == "error" and got[-1]["error"]["code"] == "budget_exhausted"
    assert llm.calls == []


def test_stream_needs_sign_in(chat_engine: Engine, settings: Settings) -> None:
    secure = settings.model_copy(update={"auth_required": True})
    with _client(chat_engine, secure, FakeLLM(grounded)) as client:
        assert client.post("/v1/chat/stream", json={"question": "x"}).status_code == 401


class BlockingLLM(FakeLLM):
    """A model that starts and never finishes (until cancelled)."""

    def __init__(
        self, started: anyio.Event, *, provider: str = "fake", model: str = "fake/scripted"
    ) -> None:
        super().__init__(grounded)
        self.provider, self.model = provider, model
        self._started = started

    async def generate(self, messages: Any, **kwargs: Any) -> GenerationResult:
        self.calls.append(messages)
        self._started.set()
        await anyio.sleep_forever()
        raise AssertionError("unreachable")


@pytest.mark.parametrize("priced", [False, True])
def test_cancelled_answer_is_recorded(
    chat_engine: Engine, settings: Settings, priced: bool
) -> None:
    use = _priced(settings) if priced else settings
    started = anyio.Event()
    llm = (
        BlockingLLM(started, provider="openai", model="gpt-6-luna")
        if priced
        else BlockingLLM(started)
    )
    finished: list[object] = []

    async def scenario() -> None:
        async with anyio.create_task_group() as group:

            async def ask() -> None:
                finished.append(
                    await answer_question(
                        chat_engine,
                        ChatRequest(question="marker37x3"),
                        use,
                        embedder=None,
                        reranker=None,
                        llm=llm,
                        nli=NLI,
                    )
                )

            group.start_soon(ask)
            await started.wait()
            group.cancel_scope.cancel()  # the reader went away

    anyio.run(scenario)
    assert finished == []  # no answer was produced
    ledger = _rows(
        chat_engine, "SELECT status, error_code, input_tokens, estimated_usd FROM llm_usage_ledger"
    )
    assert [tuple(r)[:3] for r in ledger] == [("error", "cancelled", 0)]
    expected = Decimal(0)
    if priced:  # the provider may bill it anyway: the budget counts the worst case
        price = model_price(use, "openai", "gpt-6-luna")
        assert price is not None
        tokens = estimate_request_tokens(llm.calls[0], response_schema(use.generation_max_claims))
        expected = Decimal(
            str(round(worst_case_usd(price, tokens, use.openai_max_output_tokens), 6))
        )
        assert expected > 0
    assert ledger[0].estimated_usd == expected
    assert len(_rows(chat_engine, "SELECT * FROM query_audit WHERE endpoint = '/v1/chat'")) == 1


def test_cancelled_during_search_audits_without_a_ledger_row(
    chat_engine: Engine, settings: Settings
) -> None:
    async def scenario() -> None:
        async with anyio.create_task_group() as group:

            async def on_progress(event: BaseModel) -> None:
                if isinstance(event, ChatStageEvent) and event.stage == "searching":
                    group.cancel_scope.cancel()

            async def ask() -> None:
                await answer_question(
                    chat_engine,
                    ChatRequest(question="marker37x3"),
                    settings,
                    embedder=None,
                    reranker=None,
                    llm=FakeLLM(grounded),
                    nli=NLI,
                    progress=on_progress,
                )

            group.start_soon(ask)

    anyio.run(scenario)
    assert _rows(chat_engine, "SELECT * FROM llm_usage_ledger") == []
    assert len(_rows(chat_engine, "SELECT * FROM query_audit")) == 1


def test_event_stream_cancels_the_producer_when_the_client_leaves() -> None:
    sent: list[dict[str, Any]] = []
    state = {"cancelled": False, "events": 0}

    async def produce(emit: Any) -> None:
        try:
            await emit(ChatStageEvent(stage="searching"))
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            state["cancelled"] = True
            raise

    async def receive() -> dict[str, Any]:
        while not any(m.get("body") for m in sent):  # leave after the first event
            await anyio.sleep(0.01)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def scenario() -> None:
        with anyio.fail_after(5):
            await EventStream(produce)({"type": "http"}, receive, send)

    anyio.run(scenario)
    assert state["cancelled"]
    assert sent[0]["type"] == "http.response.start"
    assert sent[1]["body"].startswith(b"event: stage\ndata: ")


SECRET = "host=db.internal user=ejudgment password=hunter2"


@pytest.fixture
def route_log(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> pytest.LogCaptureFixture:
    """The route's log. Alembic's fileConfig (run by the migration fixture) disables loggers
    that already exist; the API process itself never runs it."""
    monkeypatch.setattr(chat_route.logger, "disabled", False)
    return caplog


def _db_error(kind: type[DBAPIError]) -> DBAPIError:
    return kind("SELECT 1", {}, Exception(SECRET))


@pytest.mark.parametrize(
    ("where", "error", "code", "message"),
    [
        ("_retrieve", OperationalError, "database_unavailable", "Database is not reachable"),
        ("_retrieve", DBAPIError, "internal_error", "Unexpected database error"),
        ("_record", OperationalError, "database_unavailable", "Database is not reachable"),
    ],
)
def test_database_failures_mid_stream_end_with_an_error_event(
    chat_engine: Engine,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    route_log: pytest.LogCaptureFixture,
    where: str,
    error: type[DBAPIError],
    code: str,
    message: str,
) -> None:
    """After the stream has started the app's error handlers can't answer: the stream must
    still end with one terminal event, with the same codes and no driver details."""

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise _db_error(error)

    monkeypatch.setattr(chat_module, where, fail)
    with _client(chat_engine, settings, FakeLLM(grounded)) as client:
        response = client.post("/v1/chat/stream", json={"question": "marker37x3"})
    got = events(response.text)
    assert got[0] == {"type": "stage", "stage": "searching", "claims": None}
    assert got[-1] == {
        "type": "error",
        "error": {"code": code, "message": message, "details": None},
    }
    assert SECRET not in response.text
    assert "database error while streaming" in route_log.text  # details go to the server log


class BrokenNli(FakeNli):
    def score(self, pairs: Any) -> Any:
        raise RuntimeError("NLI runtime failed")


def test_unexpected_failure_mid_stream_ends_with_internal_error(
    chat_engine: Engine, settings: Settings, route_log: pytest.LogCaptureFixture
) -> None:
    paraphrase = FakeLLM(
        lambda messages: {
            "abstain": False,
            "claims": [
                {
                    "text": "A paraphrase that needs the NLI check.",
                    "kind": "holding",
                    "sources": ["S1"],
                    "quote": " ".join(next(iter(_sources(messages).values())).split()[:8]),
                }
            ],
            "limitations": "",
        }
    )
    with _client(chat_engine, settings, paraphrase, nli=BrokenNli()) as client:
        got = events(client.post("/v1/chat/stream", json={"question": "marker37x3"}).text)
    assert got[-1]["type"] == "error"
    assert got[-1]["error"]["code"] == "internal_error"
    assert "NLI runtime failed" not in got[-1]["error"]["message"]
    assert "NLI runtime failed" in route_log.text

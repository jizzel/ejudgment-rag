import logging
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from fastapi import APIRouter, Depends
from pydantic import BaseModel, RootModel
from sqlalchemy.exc import DBAPIError
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from ejudgment.api.dependencies import (
    CurrentUserDep,
    EngineDep,
    LLMDep,
    NLIDep,
    ProvidersDep,
    SettingsDep,
    require_user,
)
from ejudgment.api.errors import ApiError, database_error
from ejudgment.domain.schemas import (
    ChatAnswerEvent,
    ChatErrorEvent,
    ChatProgressEvent,
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    ErrorBody,
    ErrorResponse,
)
from ejudgment.generation.base import LLMUnavailable
from ejudgment.generation.budget import BudgetExhausted
from ejudgment.generation.chat import answer_question

logger = logging.getLogger(__name__)

# Every route here needs a signed-in user (see dependencies.require_user).
router = APIRouter(prefix="/v1", dependencies=[Depends(require_user)])


def _check(request: ChatRequest, llm: object, nli: object) -> None:
    """What both chat routes refuse before any work starts (as HTTP errors)."""
    if not request.question.strip():
        raise ApiError(422, "query_empty", "Question must contain text")
    if llm is None:
        raise ApiError(503, "llm_unavailable", "No language model is configured")
    if nli is None:
        # Never publish claims that could not be checked against their sources.
        raise ApiError(
            503, "verifier_unavailable", "The answer verification model is not available"
        )


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def chat(
    request: ChatRequest,
    engine: EngineDep,
    settings: SettingsDep,
    providers: ProvidersDep,
    llm: LLMDep,
    nli: NLIDep,
    user: CurrentUserDep,
) -> ChatResponse:
    """Answer from retrieved passages only; abstains (with matched cases) when it cannot."""
    _check(request, llm, nli)
    assert llm is not None and nli is not None
    embedder, reranker = providers
    try:
        return await answer_question(
            engine,
            request,
            settings,
            embedder=embedder,
            reranker=reranker,
            llm=llm,
            nli=nli,
            user_id=user.id if user else None,
        )
    except LLMUnavailable as exc:
        raise ApiError(503, "llm_unavailable", str(exc)) from exc
    except BudgetExhausted as exc:
        raise ApiError(429, "budget_exhausted", str(exc)) from exc


class ChatStreamEventDoc(RootModel[ChatStreamEvent]):
    """One server-sent event of ``POST /v1/chat/stream`` (its ``data`` line, as JSON)."""


STREAM_PATH = "/v1/chat/stream"


def document_event_stream(schema: dict[str, Any]) -> dict[str, Any]:
    """Describe the stream's 200 response as ``text/event-stream`` in the shape FastAPI uses for
    its own SSE endpoints (``itemSchema``: each event, its ``data`` a ChatStreamEventDoc). The
    route is a plain ASGI response (see :class:`EventStream`), so FastAPI would otherwise list
    it as JSON; its error responses stay JSON."""
    ok = schema["paths"][STREAM_PATH]["post"]["responses"]["200"]
    ok["content"] = {
        "text/event-stream": {
            "itemSchema": {
                "type": "object",
                "properties": {
                    "event": {"type": "string", "description": "Equals the data's type"},
                    "data": {
                        "type": "string",
                        "contentMediaType": "application/json",
                        "contentSchema": {"$ref": "#/components/schemas/ChatStreamEventDoc"},
                    },
                },
                "required": ["event", "data"],
            }
        }
    }
    return schema


Emit = Callable[[BaseModel], Awaitable[None]]


def _sse(event: BaseModel) -> bytes:
    kind = getattr(event, "type", "message")
    return f"event: {kind}\ndata: {event.model_dump_json()}\n\n".encode()


class EventStream(Response):
    """Server-sent events from ``produce``. One task produces, another watches for the client
    going away and then cancels the producer (which records what it must; see
    ``answer_question``). No async generator, so cancellation stays in one task group."""

    def __init__(self, produce: Callable[[Emit], Awaitable[None]]) -> None:
        self.produce = produce
        self.status_code = 200
        self.background = None
        self.raw_headers = [
            (b"content-type", b"text/event-stream; charset=utf-8"),
            (b"cache-control", b"no-cache, no-transform"),
            (b"x-accel-buffering", b"no"),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})

        async def emit(event: BaseModel) -> None:
            await send({"type": "http.response.body", "body": _sse(event), "more_body": True})

        async with anyio.create_task_group() as group:

            async def watch() -> None:
                while (await receive())["type"] != "http.disconnect":
                    pass
                group.cancel_scope.cancel()

            async def run() -> None:
                await self.produce(emit)
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                group.cancel_scope.cancel()

            group.start_soon(watch)
            group.start_soon(run)


@router.post(
    "/chat/stream",
    response_model=None,
    responses={
        200: {
            "model": ChatStreamEventDoc,
            "description": "Server-sent events, in order: stage and sources events, then exactly "
            "one answer or error event. The schema describes one event's data line (JSON); "
            "the event name equals its type.",
        },
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def chat_stream(
    request: ChatRequest,
    engine: EngineDep,
    settings: SettingsDep,
    providers: ProvidersDep,
    llm: LLMDep,
    nli: NLIDep,
    user: CurrentUserDep,
) -> Response:
    """The same answer as ``/v1/chat``, streamed: progress stages and the passages sent to the
    model while it works, then the answer. Errors after the stream has started arrive as an
    ``error`` event with the JSON route's codes. Closing the connection cancels the answer
    (an in-flight model call is aborted and recorded as cancelled)."""
    _check(request, llm, nli)
    assert llm is not None and nli is not None
    embedder, reranker = providers

    async def produce(emit: Emit) -> None:
        async def progress(event: ChatProgressEvent) -> None:
            await emit(event)

        def failed(code: str, message: str) -> ChatErrorEvent:
            return ChatErrorEvent(error=ErrorBody(code=code, message=message))

        try:
            answer = await answer_question(
                engine,
                request,
                settings,
                embedder=embedder,
                reranker=reranker,
                llm=llm,
                nli=nli,
                user_id=user.id if user else None,
                progress=progress,
            )
        except LLMUnavailable as exc:
            await emit(failed("llm_unavailable", str(exc)))
        except BudgetExhausted as exc:
            await emit(failed("budget_exhausted", str(exc)))
        # The response has started, so the app's error handlers can no longer answer: every
        # stream still ends with one terminal event, with the same codes and generic messages.
        # (Cancellation is not an Exception and is never reported here.)
        except DBAPIError as exc:
            _, code, message = database_error(exc)
            logger.exception("database error while streaming an answer")
            await emit(failed(code, message))
        except Exception:
            logger.exception("unexpected error while streaming an answer")
            await emit(failed("internal_error", "Unexpected error while preparing the answer"))
        else:
            await emit(ChatAnswerEvent(answer=answer))

    return EventStream(produce)

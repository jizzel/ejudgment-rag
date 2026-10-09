from fastapi import APIRouter

from ejudgment.api.dependencies import EngineDep, LLMDep, NLIDep, ProvidersDep, SettingsDep
from ejudgment.api.errors import ApiError
from ejudgment.domain.schemas import ChatRequest, ChatResponse, ErrorResponse
from ejudgment.generation.base import LLMUnavailable
from ejudgment.generation.chat import answer_question

router = APIRouter(prefix="/v1")


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def chat(
    request: ChatRequest,
    engine: EngineDep,
    settings: SettingsDep,
    providers: ProvidersDep,
    llm: LLMDep,
    nli: NLIDep,
) -> ChatResponse:
    """Answer from retrieved passages only; abstains (with matched cases) when it cannot."""
    if not request.question.strip():
        raise ApiError(422, "query_empty", "Question must contain text")
    if llm is None:
        raise ApiError(503, "llm_unavailable", "No language model is configured")
    if nli is None:
        # Never publish claims that could not be checked against their sources.
        raise ApiError(
            503, "verifier_unavailable", "The answer verification model is not available"
        )
    embedder, reranker = providers
    try:
        return await answer_question(
            engine, request, settings, embedder=embedder, reranker=reranker, llm=llm, nli=nli
        )
    except LLMUnavailable as exc:
        raise ApiError(503, "llm_unavailable", str(exc)) from exc

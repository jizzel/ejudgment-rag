import time

from fastapi import APIRouter, Depends

from ejudgment.api.dependencies import (
    ConnectionDep,
    CurrentUserDep,
    ProvidersDep,
    SettingsDep,
    require_user,
)
from ejudgment.api.errors import ApiError
from ejudgment.domain.schemas import ErrorResponse, SearchRequest, SearchResponse
from ejudgment.retrieval.service import SearchDepthExceeded, record_audit, search

# Every route here needs a signed-in user (see dependencies.require_user).
router = APIRouter(prefix="/v1", dependencies=[Depends(require_user)])


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={422: {"model": ErrorResponse}},
)
def search_judgments(
    request: SearchRequest,
    conn: ConnectionDep,
    settings: SettingsDep,
    providers: ProvidersDep,
    user: CurrentUserDep,
) -> SearchResponse:
    if not request.query.strip():
        raise ApiError(422, "query_empty", "Query must contain text")
    if request.top_k > settings.search_max_top_k:
        raise ApiError(422, "invalid_request", f"top_k must be <= {settings.search_max_top_k}")
    embedder, reranker = providers
    started = time.perf_counter()
    try:
        response = search(conn, request, settings, embedder=embedder, reranker=reranker)
    except SearchDepthExceeded as exc:
        raise ApiError(422, "invalid_request", str(exc)) from exc
    judgment_ids = [case.judgment.judgment_id for case in response.cases]
    record_audit(
        conn,
        request.query,
        request.filters,
        judgment_ids,
        started,
        settings,
        endpoint="/v1/search",
        user_id=user.id if user else None,
    )
    return response

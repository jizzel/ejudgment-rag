import uuid

from fastapi import APIRouter, Query

from ejudgment.api.dependencies import ConnectionDep, SettingsDep
from ejudgment.api.errors import ApiError
from ejudgment.domain.schemas import CourtsResponse, ErrorResponse, PassageContext
from ejudgment.retrieval.service import list_courts, passage_context

router = APIRouter(prefix="/v1")


@router.get(
    "/passages/{chunk_id}",
    response_model=PassageContext,
    responses={404: {"model": ErrorResponse}},
)
def read_passage(
    chunk_id: uuid.UUID,
    conn: ConnectionDep,
    settings: SettingsDep,
    context: int = Query(default=1, ge=0, le=3, description="Neighbouring passages per side"),
) -> PassageContext:
    """A passage of an eligible judgment with its neighbours, for reading in context."""
    result = passage_context(conn, chunk_id, context, settings)
    if result is None:
        raise ApiError(404, "passage_not_found", f"No eligible passage {chunk_id}")
    return result


@router.get("/courts", response_model=CourtsResponse)
def read_courts(conn: ConnectionDep) -> CourtsResponse:
    """Courts with eligible judgments (for search filters)."""
    return list_courts(conn)

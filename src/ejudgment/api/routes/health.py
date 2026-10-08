from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ejudgment.api.dependencies import EngineDep
from ejudgment.api.errors import DATABASE_UNAVAILABLE, ApiError

router = APIRouter()


@router.get("/healthz")
def healthz(engine: EngineDep) -> dict[str, str]:
    # The connection is opened here, inside the try, so an outage while connecting is reported
    # as 503 too (a connection dependency would fail before this body runs).
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ApiError(503, DATABASE_UNAVAILABLE, "Database is not reachable") from exc
    return {"status": "ok"}

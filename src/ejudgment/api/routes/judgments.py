import uuid

from fastapi import APIRouter, Depends

from ejudgment.api.dependencies import ConnectionDep, SettingsDep, require_user
from ejudgment.api.errors import ApiError
from ejudgment.domain.schemas import ErrorResponse, JudgmentDetail
from ejudgment.retrieval.service import get_judgment

# Every route here needs a signed-in user (see dependencies.require_user).
router = APIRouter(prefix="/v1", dependencies=[Depends(require_user)])


@router.get(
    "/judgments/{judgment_id}",
    response_model=JudgmentDetail,
    responses={404: {"model": ErrorResponse}},
)
def read_judgment(
    judgment_id: uuid.UUID, conn: ConnectionDep, settings: SettingsDep
) -> JudgmentDetail:
    detail = get_judgment(conn, judgment_id, settings)
    if detail is None:
        raise ApiError(404, "judgment_not_found", f"No eligible judgment {judgment_id}")
    return detail

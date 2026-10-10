from typing import Any

from fastapi import APIRouter, Request

from ejudgment.api.dependencies import (
    CurrentUserDep,
    EngineDep,
    SettingsDep,
    bearer_token,
    client_address,
)
from ejudgment.api.errors import ApiError
from ejudgment.auth.passwords import WeakPassword
from ejudgment.auth.service import UNAUTHENTICATED, AuthError, AuthUser
from ejudgment.auth.service import change_password as change_user_password
from ejudgment.auth.service import login as start_session
from ejudgment.auth.service import logout as end_session
from ejudgment.domain.schemas import (
    ErrorResponse,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    UserInfo,
)

router = APIRouter(prefix="/v1/auth")
_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


def _info(user: AuthUser) -> UserInfo:
    return UserInfo(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


def _signed_in(user: AuthUser | None) -> AuthUser:
    if user is None:  # only possible with auth_required off and no token
        raise UNAUTHENTICATED
    return user


@router.post("/login", response_model=LoginResponse, responses=_ERRORS)
def login(
    body: LoginRequest, request: Request, engine: EngineDep, settings: SettingsDep
) -> LoginResponse:
    """Sign in with email and password. Returns a bearer token (send it as
    ``Authorization: Bearer <token>``)."""
    error: AuthError | None = None
    # Its own transaction, committed even when the sign-in fails: failures must be recorded
    # for the lockout to work.
    with engine.begin() as conn:
        try:
            session = start_session(
                conn, settings, body.email, body.password, client=client_address(request)
            )
        except AuthError as exc:
            error = exc
    if error is not None:
        raise error
    return LoginResponse(
        token=session.token, expires_at=session.expires_at, user=_info(session.user)
    )


@router.post("/logout", status_code=204, responses=_ERRORS)
def logout(
    request: Request, user: CurrentUserDep, engine: EngineDep, settings: SettingsDep
) -> None:
    token = bearer_token(request)
    if token is None:
        raise UNAUTHENTICATED
    with engine.begin() as conn:
        end_session(conn, settings, token, _signed_in(user))


@router.get("/me", response_model=UserInfo, responses=_ERRORS)
def me(user: CurrentUserDep) -> UserInfo:
    return _info(_signed_in(user))


@router.post("/password", status_code=204, responses={**_ERRORS, 403: {"model": ErrorResponse}})
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    user: CurrentUserDep,
    engine: EngineDep,
    settings: SettingsDep,
) -> None:
    """Change your own password (current password required); ends your other sessions."""
    token = bearer_token(request)
    if token is None:
        raise UNAUTHENTICATED
    try:
        with engine.begin() as conn:
            change_user_password(
                conn,
                settings,
                _signed_in(user),
                current_password=body.current_password,
                new_password=body.new_password,
                token=token,
            )
    except WeakPassword as exc:
        raise ApiError(422, "weak_password", str(exc)) from exc

"""Stable error codes: every error body is ``{"error": {"code", "message", "details"}}``."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ejudgment.auth.service import AuthError
from ejudgment.domain.schemas import ErrorBody, ErrorResponse
from ejudgment.evaluation.gold_review import GoldReviewError

DATABASE_UNAVAILABLE = "database_unavailable"


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(
    status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


def _validation_code(errors: list[dict[str, Any]]) -> str:
    for error in errors:
        location = [str(part) for part in error.get("loc", ())]
        if "filters" in location:
            return "invalid_filter"
        if location[-1:] == ["query"] and error.get("type") in ("string_too_short", "missing"):
            return "query_empty"
    return "invalid_request"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(GoldReviewError)
    async def _review_error(_: Request, exc: GoldReviewError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
        response = error_response(exc.status, exc.code, exc.message)
        if exc.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return error_response(422, _validation_code(errors), "Request validation failed", errors)

    @app.exception_handler(OperationalError)
    async def _database_down(_: Request, exc: OperationalError) -> JSONResponse:
        # Raised while connecting (e.g. in a connection dependency) or on a lost connection.
        # The message stays generic: driver errors can include host and user names.
        return error_response(503, DATABASE_UNAVAILABLE, "Database is not reachable")

    @app.exception_handler(DBAPIError)
    async def _database_error(_: Request, exc: DBAPIError) -> JSONResponse:
        if exc.connection_invalidated:
            return error_response(503, DATABASE_UNAVAILABLE, "Database is not reachable")
        return error_response(500, "internal_error", "Unexpected database error")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error_response(exc.status_code, code, str(exc.detail))

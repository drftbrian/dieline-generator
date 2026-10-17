"""Uniform error responses: what happened (message), what to do next (hint).

Every error body has the shape ``{"error": {"code", "message", "hint", "details"}}`` so the
frontend can branch on ``code`` and show ``message``/``hint`` verbatim.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None = None
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = ErrorBody(code=code, message=message, hint=hint, details=details or {})


def _respond(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=ErrorResponse(error=body).model_dump())


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _respond(exc.status_code, exc.body)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _respond(
            422,
            ErrorBody(
                code="VALIDATION_ERROR",
                message="요청 형식이 올바르지 않습니다.",
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else f"HTTP_{exc.status_code}"
        return _respond(exc.status_code, ErrorBody(code=code, message=str(exc.detail)))

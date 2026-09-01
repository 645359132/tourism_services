"""Shared application exceptions and JSON error responses."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An expected error that can be safely returned to an API caller."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    content: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        },
        "request_id": request_id,
    }
    if details is not None:
        content["error"]["details"] = jsonable_encoder(details)
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"X-Request-ID": request_id},
    )


def _http_error_code(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name
    except ValueError:
        return f"HTTP_{status_code}"


def register_exception_handlers(app: FastAPI) -> None:
    """Install one stable error envelope across framework and domain errors."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        details = None if isinstance(exc.detail, str) else exc.detail
        return _error_response(
            request,
            status_code=exc.status_code,
            code=_http_error_code(exc.status_code),
            message=message,
            details=details,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
        )

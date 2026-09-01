"""Request correlation and access logging middleware."""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging import request_id_context

logger = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlate every response and access log with a request ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = (
            supplied_request_id
            if supplied_request_id and len(supplied_request_id) <= 128
            else uuid4().hex
        )
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started_at = perf_counter()

        try:
            response = await call_next(request)
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "%s %s completed with %s in %.2fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        except Exception:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "%s %s failed in %.2fms",
                request.method,
                request.url.path,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                },
            )
            raise
        finally:
            request_id_context.reset(token)

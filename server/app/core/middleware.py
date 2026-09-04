"""Request correlation and access logging middleware."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from ipaddress import ip_address, ip_network
from time import perf_counter
from uuid import uuid4

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.coordination import CoordinationUnavailableError
from app.core.logging import request_id_context
from app.core.security import decode_token

logger = logging.getLogger("app.access")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def safe_request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


@lru_cache(maxsize=128)
def _parsed_proxy_networks(values: tuple[str, ...]) -> tuple[object, ...]:
    return tuple(ip_network(value, strict=False) for value in values)


def _is_trusted_proxy(address: object, networks: tuple[object, ...]) -> bool:
    return any(address in network for network in networks)  # type: ignore[operator]


def rate_limit_client_identity(request: Request) -> str:
    """Use forwarded client IPs only when the direct peer is explicitly trusted."""

    peer = request.client.host if request.client is not None else "unknown"
    configured = tuple(request.app.state.settings.trusted_proxy_networks)
    if not configured:
        return peer
    try:
        peer_address = ip_address(peer)
        networks = _parsed_proxy_networks(configured)
    except ValueError:
        return peer
    if not _is_trusted_proxy(peer_address, networks):
        return peer

    raw_forwarded = request.headers.get("X-Forwarded-For", "")
    try:
        forwarded = [
            ip_address(value.strip()) for value in raw_forwarded.split(",") if value.strip()
        ]
    except ValueError:
        return peer
    if not forwarded:
        return peer
    for address in reversed(forwarded):
        if not _is_trusted_proxy(address, networks):
            return str(address)
    return str(forwarded[0])


def apply_security_headers(request: Request, response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    documentation_path = request.url.path
    if not (
        documentation_path.startswith("/docs")
        or documentation_path.startswith("/redoc")
        or documentation_path == "/openapi.json"
    ):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        )
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


def apply_cors_headers(request: Request, response: Response) -> Response:
    """Apply simple-response CORS headers for outer 500 error handling."""

    origin = request.headers.get("Origin")
    if not origin:
        return response
    settings = request.app.state.settings
    if "*" in settings.cors_origins:
        allowed_origin = origin if settings.cors_allow_credentials else "*"
    elif origin in settings.cors_origins:
        allowed_origin = origin
    else:
        return response
    response.headers["Access-Control-Allow-Origin"] = allowed_origin
    if settings.cors_allow_credentials:
        response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers.add_vary_header("Origin")
    return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlate every response and access log with a request ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = safe_request_id(request.headers.get("X-Request-ID"))
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply production-safe browser and transport response headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        return apply_security_headers(request, response)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Bound auth, WS-ticket, and mutating API traffic via coordination."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = request.app.state.settings
        selected = self._selected_limit(request)
        if not settings.rate_limit_enabled or selected is None:
            return await call_next(request)
        category, limit = selected
        actor = rate_limit_client_identity(request)
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        # Authentication endpoints stay bound to the network identity. Otherwise
        # a registered caller could rotate valid bearer subjects to evade the
        # login/registration quota while forcing password hashing and SQL writes.
        if category != "auth" and scheme.lower() == "bearer" and token:
            try:
                claims = decode_token(
                    token,
                    expected_type="access",
                    settings=settings,
                )
            except jwt.InvalidTokenError:
                pass
            else:
                actor = f"user:{claims['sub']}"
        key = f"{category}:{actor}"
        backend = request.app.state.rate_limit_backend
        degraded = False
        try:
            decision = await backend.rate_limit(
                key=key,
                limit=limit,
                window_seconds=settings.rate_limit_window_seconds,
            )
        except CoordinationUnavailableError:
            if settings.redis_required:
                request_id = getattr(request.state, "request_id", safe_request_id(None))
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": {
                            "code": "COORDINATION_UNAVAILABLE",
                            "message": "Distributed coordination is temporarily unavailable",
                        },
                        "request_id": request_id,
                    },
                    headers={"Retry-After": "1"},
                )
            fallback = request.app.state.local_coordination
            decision = await fallback.rate_limit(
                key=key,
                limit=limit,
                window_seconds=settings.rate_limit_window_seconds,
            )
            degraded = True
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.retry_after_seconds),
        }
        if degraded:
            headers["X-Coordination-Mode"] = "local-degraded"
        if not decision.allowed:
            headers["Retry-After"] = str(decision.retry_after_seconds)
            request_id = getattr(request.state, "request_id", safe_request_id(None))
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests",
                    },
                    "request_id": request_id,
                },
                headers=headers,
            )
        response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response

    @staticmethod
    def _selected_limit(request: Request) -> tuple[str, int] | None:
        settings = request.app.state.settings
        path = request.url.path
        if not path.startswith("/api/v1") or request.method == "OPTIONS":
            return None
        if request.method == "POST" and path.endswith("/ws-tickets"):
            return "ws-ticket", settings.rate_limit_ws_ticket_requests
        if request.method == "POST" and path in {
            "/api/v1/auth/register",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
        }:
            return "auth", settings.rate_limit_auth_requests
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return "mutation", settings.rate_limit_mutation_requests
        return None

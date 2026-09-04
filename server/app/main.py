"""FastAPI application factory and development entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.coordination import (
    CoordinationBackend,
    CoordinationLockManager,
    CoordinationUnavailableError,
    LocalCoordinationBackend,
    RedisCoordinationBackend,
    ReferenceCache,
)
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import dispose_database, get_session_factory
from app.realtime.crowd import ConnectionHub, CrowdPublisher
from app.realtime.queues import QueueConnectionHub, QueuePublisher, QueueTicketStore
from app.realtime.support import SupportConnectionHub, SupportTicketStore

logger = logging.getLogger(__name__)


def _configure_coordination(
    application: FastAPI,
    redis_backend: CoordinationBackend | None,
) -> None:
    settings: Settings = application.state.settings
    local: LocalCoordinationBackend = application.state.local_coordination

    def feature_backend(enabled: bool) -> CoordinationBackend:
        return redis_backend if redis_backend is not None and enabled else local

    application.state.rate_limit_backend = feature_backend(settings.redis_rate_limit_enabled)
    application.state.reference_cache.configure_backend(
        feature_backend(settings.redis_cache_enabled)
    )
    application.state.coordination_locks.configure_backend(
        feature_backend(settings.redis_lock_enabled)
    )
    leader_backend = feature_backend(settings.redis_lock_enabled)
    application.state.crowd_publisher.configure_leader_backend(leader_backend)
    application.state.queue_publisher.configure_leader_backend(leader_backend)
    ticket_backend = feature_backend(settings.redis_ticket_enabled)
    application.state.queue_tickets.configure_backend(ticket_backend)
    application.state.support_tickets.configure_backend(ticket_backend)
    event_backend = feature_backend(settings.redis_pubsub_enabled)
    application.state.crowd_hub.configure_backend(event_backend)
    application.state.queue_hub.configure_backend(event_backend)
    application.state.support_hub.configure_backend(event_backend)
    application.state.coordination_mode = "redis" if redis_backend is not None else "local"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    redis_backend: CoordinationBackend | None = application.state.redis_coordination
    active_redis: CoordinationBackend | None = None
    if redis_backend is not None:
        try:
            await redis_backend.start()
            active_redis = redis_backend
        except CoordinationUnavailableError:
            if settings.redis_required:
                raise
            logger.warning("Redis unavailable at startup; using local coordination")
    _configure_coordination(application, active_redis)
    try:
        await application.state.crowd_hub.start()
        await application.state.queue_hub.start()
        await application.state.support_hub.start()
    except CoordinationUnavailableError:
        if settings.redis_required:
            if redis_backend is not None:
                await redis_backend.close()
            raise
        logger.warning("Redis pub/sub unavailable at startup; using local coordination")
        if redis_backend is not None:
            await redis_backend.close()
        active_redis = None
        _configure_coordination(application, None)

    crowd_publisher: CrowdPublisher = application.state.crowd_publisher
    queue_publisher: QueuePublisher = application.state.queue_publisher
    crowd_publisher.start()
    queue_publisher.start()
    try:
        yield
    finally:
        await queue_publisher.stop()
        await crowd_publisher.stop()
        if active_redis is not None:
            await active_redis.close()
        await dispose_database()


def create_app(
    settings: Settings | None = None,
    *,
    redis_backend: CoordinationBackend | None = None,
) -> FastAPI:
    """Build an independently configurable FastAPI application."""

    resolved_settings = settings or get_settings()
    configure_logging(
        resolved_settings.log_level,
        json_logs=resolved_settings.log_json,
    )

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    local_coordination = LocalCoordinationBackend()
    application.state.local_coordination = local_coordination
    if resolved_settings.redis_coordination_enabled and resolved_settings.redis_url:
        application.state.redis_coordination = redis_backend or RedisCoordinationBackend(
            url=resolved_settings.redis_url,
            prefix=resolved_settings.redis_key_prefix,
            socket_timeout_seconds=resolved_settings.redis_socket_timeout_seconds,
        )
    else:
        application.state.redis_coordination = None
    application.state.rate_limit_backend = local_coordination
    application.state.reference_cache = ReferenceCache(
        backend=local_coordination,
        fallback=local_coordination,
        ttl_seconds=resolved_settings.reference_cache_ttl_seconds,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.coordination_locks = CoordinationLockManager(
        backend=local_coordination,
        fallback=local_coordination,
        ttl_seconds=resolved_settings.coordination_claim_ttl_seconds,
        wait_seconds=resolved_settings.coordination_lock_wait_seconds,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.coordination_mode = "local"
    application.state.crowd_hub = ConnectionHub(
        backend=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.crowd_publisher = CrowdPublisher(
        hub=application.state.crowd_hub,
        session_factory_provider=get_session_factory,
        interval_seconds=resolved_settings.crowd_publish_interval_seconds,
        leader_backend=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.queue_hub = QueueConnectionHub(
        backend=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.queue_tickets = QueueTicketStore(
        ttl_seconds=resolved_settings.ws_ticket_ttl_seconds,
        backend=local_coordination,
        fallback=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.queue_publisher = QueuePublisher(
        hub=application.state.queue_hub,
        session_factory_provider=get_session_factory,
        interval_seconds=resolved_settings.queue_publish_interval_seconds,
        leader_backend=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.support_hub = SupportConnectionHub(
        backend=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )
    application.state.support_tickets = SupportTicketStore(
        ttl_seconds=resolved_settings.ws_ticket_ttl_seconds,
        backend=local_coordination,
        fallback=local_coordination,
        allow_degraded=not resolved_settings.redis_required,
    )

    register_exception_handlers(application)
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=resolved_settings.trusted_hosts,
        www_redirect=False,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=resolved_settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if resolved_settings.security_headers_enabled:
        application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.include_router(api_router)
    return application


app = create_app()


def run() -> None:
    """Run the local development server through the project script."""

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=False,
        reload=settings.debug and settings.app_env == "development",
        log_config=None,
    )


if __name__ == "__main__":
    run()

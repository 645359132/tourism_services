"""Distributed coordination, fallback, and runtime hardening tests."""

from __future__ import annotations

import asyncio
from fnmatch import fnmatchcase
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.coordination import (
    CoordinationBusyError,
    CoordinationLockManager,
    CoordinationUnavailableError,
    LocalCoordinationBackend,
    RedisCoordinationBackend,
    ReferenceCache,
)
from app.core.middleware import RateLimitMiddleware
from app.core.security import create_access_token
from app.main import create_app
from app.realtime.crowd import ConnectionHub, CrowdPublisher
from app.realtime.queues import QueueConnectionHub, QueuePublisher, QueueTicketStore
from app.realtime.support import SupportTicketStore
from app.schemas.guide import CrowdWebSocketEnvelope


class TrackingBackend(LocalCoordinationBackend):
    distributed = True

    def __init__(
        self,
        *,
        fail_operations: set[str] | None = None,
        fail_start: bool = False,
    ) -> None:
        super().__init__()
        self.calls: list[str] = []
        self.fail_operations = fail_operations or set()
        self.fail_start = fail_start
        self.handlers: list[tuple[str, object]] = []
        self.rate_requests: list[dict[str, object]] = []
        self.pubsub_is_healthy = True

    @property
    def pubsub_healthy(self) -> bool:
        return self.pubsub_is_healthy

    def _record(self, operation: str) -> None:
        self.calls.append(operation)
        if operation in self.fail_operations:
            raise CoordinationUnavailableError(f"{operation} unavailable")

    async def start(self) -> None:
        self._record("start")
        if self.fail_start:
            raise CoordinationUnavailableError("startup unavailable")

    async def close(self) -> None:
        self.calls.append("close")

    async def rate_limit(self, **kwargs):  # type: ignore[no-untyped-def]
        self._record("rate_limit")
        self.rate_requests.append(dict(kwargs))
        return await super().rate_limit(**kwargs)

    async def cache_get(self, key: str) -> str | None:
        self._record("cache_get")
        return await super().cache_get(key)

    async def cache_set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._record("cache_set")
        await super().cache_set(key, value, ttl_seconds)

    async def claim(self, **kwargs):  # type: ignore[no-untyped-def]
        self._record("claim")
        return await super().claim(**kwargs)

    async def release_claim(self, **kwargs):  # type: ignore[no-untyped-def]
        self._record("release_claim")
        await super().release_claim(**kwargs)

    async def ticket_put(self, **kwargs):  # type: ignore[no-untyped-def]
        self._record("ticket_put")
        return await super().ticket_put(**kwargs)

    async def ticket_take(self, key: str) -> str | None:
        self._record("ticket_take")
        return await super().ticket_take(key)

    async def publish(self, topic: str, payload: str) -> None:
        self._record("publish")
        for pattern, handler in tuple(self.handlers):
            if fnmatchcase(topic, pattern):
                await handler(topic, payload)  # type: ignore[operator]

    async def subscribe(self, pattern: str, handler) -> None:  # type: ignore[no-untyped-def]
        self._record("subscribe")
        self.handlers.append((pattern, handler))


class ProbeResponse(BaseModel):
    value: str


@pytest.mark.asyncio
async def test_local_coordination_primitives_are_atomic() -> None:
    backend = LocalCoordinationBackend()

    first = await backend.rate_limit(key="actor", limit=1, window_seconds=60)
    second = await backend.rate_limit(key="actor", limit=1, window_seconds=60)
    assert first.allowed is True
    assert second.allowed is False

    await backend.cache_set("reference", "value", 60)
    assert await backend.cache_get("reference") == "value"
    assert await backend.claim(key="work", owner="one", ttl_seconds=60) is True
    assert await backend.claim(key="work", owner="two", ttl_seconds=60) is False
    await backend.release_claim(key="work", owner="two")
    assert await backend.claim(key="work", owner="two", ttl_seconds=60) is False
    await backend.release_claim(key="work", owner="one")
    assert await backend.claim(key="work", owner="two", ttl_seconds=60) is True

    assert await backend.ticket_put(key="once", payload="grant", ttl_seconds=60) is True
    assert await backend.ticket_take("once") == "grant"
    assert await backend.ticket_take("once") is None


@pytest.mark.asyncio
async def test_reference_cache_and_locks_degrade_only_when_allowed() -> None:
    fallback = LocalCoordinationBackend()
    unavailable = TrackingBackend(fail_operations={"cache_get", "cache_set", "claim"})
    cache = ReferenceCache(
        backend=unavailable,
        fallback=fallback,
        ttl_seconds=60,
    )
    loads = 0

    async def load() -> ProbeResponse:
        nonlocal loads
        loads += 1
        return ProbeResponse(value="sql")

    assert (await cache.get_or_load(key="probe", model=ProbeResponse, loader=load)).value == "sql"
    assert (await cache.get_or_load(key="probe", model=ProbeResponse, loader=load)).value == "sql"
    assert loads == 1

    locks = CoordinationLockManager(
        backend=unavailable,
        fallback=fallback,
        ttl_seconds=30,
        wait_seconds=0,
    )
    async with locks.hold("inventory:item"):
        pass

    required_cache = ReferenceCache(
        backend=unavailable,
        fallback=fallback,
        ttl_seconds=60,
        allow_degraded=False,
    )
    with pytest.raises(CoordinationUnavailableError):
        await required_cache.get_or_load(
            key="required",
            model=ProbeResponse,
            loader=load,
        )

    assert await fallback.claim(
        key="lock:busy",
        owner="other",
        ttl_seconds=60,
    )
    busy = CoordinationLockManager(
        backend=fallback,
        fallback=fallback,
        ttl_seconds=30,
        wait_seconds=0,
    )
    with pytest.raises(CoordinationBusyError):
        async with busy.hold("busy"):
            pass


@pytest.mark.asyncio
async def test_distributed_ticket_stores_are_one_use_and_recover_local_issue() -> None:
    fallback = LocalCoordinationBackend()
    backend = TrackingBackend()
    queue_store = QueueTicketStore(
        ttl_seconds=60,
        backend=backend,
        fallback=fallback,
    )
    user_id = uuid4()
    queue_id = uuid4()
    token, _ = await queue_store.issue(user_id=user_id, queue_id=queue_id)
    assert await queue_store.consume(token=token, queue_id=uuid4()) is None
    assert await queue_store.consume(token=token, queue_id=queue_id) is None

    backend.fail_operations.add("ticket_put")
    recovered_token, _ = await queue_store.issue(user_id=user_id, queue_id=queue_id)
    backend.fail_operations.clear()
    recovered = await queue_store.consume(token=recovered_token, queue_id=queue_id)
    assert recovered is not None
    assert recovered.user_id == user_id

    support_store = SupportTicketStore(
        ttl_seconds=60,
        backend=backend,
        fallback=fallback,
    )
    conversation_id = uuid4()
    support_token, _ = await support_store.issue(
        user_id=user_id,
        conversation_id=conversation_id,
    )
    assert (
        await support_store.consume(
            token=support_token,
            conversation_id=conversation_id,
        )
    ) is not None
    assert (
        await support_store.consume(
            token=support_token,
            conversation_id=conversation_id,
        )
    ) is None
    backend.fail_operations.add("ticket_put")
    local_support_token, _ = await support_store.issue(
        user_id=user_id,
        conversation_id=conversation_id,
    )
    backend.fail_operations.clear()
    assert (
        await support_store.consume(
            token=local_support_token,
            conversation_id=conversation_id,
        )
    ) is not None
    assert {"ticket_put", "ticket_take"}.issubset(backend.calls)


@pytest.mark.asyncio
async def test_redis_ticket_consumed_on_worker_b_cannot_replay_on_worker_a() -> None:
    backend = TrackingBackend()
    user_id = uuid4()

    queue_id = uuid4()
    queue_a = QueueTicketStore(
        ttl_seconds=60,
        backend=backend,
        fallback=LocalCoordinationBackend(),
    )
    queue_b = QueueTicketStore(
        ttl_seconds=60,
        backend=backend,
        fallback=LocalCoordinationBackend(),
    )
    queue_token, _ = await queue_a.issue(user_id=user_id, queue_id=queue_id)
    assert await queue_b.consume(token=queue_token, queue_id=queue_id) is not None
    backend.fail_operations.add("ticket_take")
    assert await queue_a.consume(token=queue_token, queue_id=queue_id) is None

    backend.fail_operations.clear()
    conversation_id = uuid4()
    support_a = SupportTicketStore(
        ttl_seconds=60,
        backend=backend,
        fallback=LocalCoordinationBackend(),
    )
    support_b = SupportTicketStore(
        ttl_seconds=60,
        backend=backend,
        fallback=LocalCoordinationBackend(),
    )
    support_token, _ = await support_a.issue(
        user_id=user_id,
        conversation_id=conversation_id,
    )
    assert (
        await support_b.consume(
            token=support_token,
            conversation_id=conversation_id,
        )
    ) is not None
    backend.fail_operations.add("ticket_take")
    assert (
        await support_a.consume(
            token=support_token,
            conversation_id=conversation_id,
        )
    ) is None


@pytest.mark.asyncio
async def test_crowd_pubsub_delivers_remote_once_and_ignores_echo() -> None:
    backend = TrackingBackend()
    first = ConnectionHub(backend=backend)
    second = ConnectionHub(backend=backend)
    await first.start()
    await second.start()
    _, local_messages = first.register()
    _, remote_messages = second.register()
    envelope = CrowdWebSocketEnvelope(
        id="event-1",
        type="crowd.updated",
        occurred_at="2026-09-04T00:00:00Z",
        data={"sequence": 1},
    )

    await first.broadcast(envelope)

    assert (await local_messages.get()).id == "event-1"
    assert local_messages.empty()
    assert (await remote_messages.get()).id == "event-1"
    assert {"subscribe", "publish"}.issubset(backend.calls)


@pytest.mark.asyncio
async def test_publishers_use_one_distributed_tick_leader() -> None:
    backend = TrackingBackend()
    first = CrowdPublisher(
        hub=ConnectionHub(),
        session_factory_provider=lambda: None,  # type: ignore[arg-type]
        interval_seconds=30,
        leader_backend=backend,
    )
    second = CrowdPublisher(
        hub=ConnectionHub(),
        session_factory_provider=lambda: None,  # type: ignore[arg-type]
        interval_seconds=30,
        leader_backend=backend,
    )

    assert await first._is_tick_leader() is True
    assert await second._is_tick_leader() is False
    assert [request["key"] for request in backend.rate_requests] == [
        "publisher:crowd",
        "publisher:crowd",
    ]
    assert all(request["window_seconds"] == 30 for request in backend.rate_requests)
    assert "claim" not in backend.calls

    queue_first = QueuePublisher(
        hub=QueueConnectionHub(),
        session_factory_provider=lambda: None,  # type: ignore[arg-type]
        interval_seconds=15,
        leader_backend=backend,
    )
    queue_second = QueuePublisher(
        hub=QueueConnectionHub(),
        session_factory_provider=lambda: None,  # type: ignore[arg-type]
        interval_seconds=15,
        leader_backend=backend,
    )
    assert await queue_first._is_tick_leader() is True
    assert await queue_second._is_tick_leader() is False
    assert [request["key"] for request in backend.rate_requests[-2:]] == [
        "publisher:queue",
        "publisher:queue",
    ]


class StubPubSub:
    def __init__(
        self,
        *,
        responses: list[dict[str, object] | Exception | None] | None = None,
        failed: asyncio.Event | None = None,
    ) -> None:
        self.responses = responses or []
        self.failed = failed
        self.patterns: list[str] = []
        self.closed = False
        self._hold = asyncio.Event()

    async def psubscribe(self, pattern: str) -> None:
        self.patterns.append(pattern)

    async def aclose(self) -> None:
        self.closed = True

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,  # noqa: ASYNC109 - mirrors redis-py's public API
    ) -> dict[str, object] | None:
        del ignore_subscribe_messages, timeout
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                if self.failed is not None:
                    self.failed.set()
                raise response
            return response
        await self._hold.wait()
        return None


class StubRedisClient:
    def __init__(self, pubsubs: list[StubPubSub]) -> None:
        self.pubsubs = pubsubs

    def pubsub(self) -> StubPubSub:
        return self.pubsubs.pop(0)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_pubsub_retries_and_resubscribes_after_disconnect() -> None:
    failed = asyncio.Event()
    first = StubPubSub(responses=[RedisError("connection lost")], failed=failed)
    second = StubPubSub(
        responses=[
            {
                "type": "pmessage",
                "channel": "tourism:events:crowd",
                "data": "recovered",
            }
        ]
    )
    backend = RedisCoordinationBackend(url="redis://unused")
    backend.client = StubRedisClient([first, second])  # type: ignore[assignment]
    received = asyncio.Event()
    payloads: list[tuple[str, str]] = []

    async def handler(topic: str, payload: str) -> None:
        payloads.append((topic, payload))
        received.set()

    await backend.subscribe("crowd", handler)
    await asyncio.wait_for(failed.wait(), timeout=1)
    assert backend.pubsub_healthy is False
    await asyncio.wait_for(received.wait(), timeout=1)
    assert backend.pubsub_healthy is True
    assert first.closed is True
    assert second.patterns == ["tourism:events:crowd"]
    assert payloads == [("crowd", "recovered")]

    await backend.close()
    assert second.closed is True


@pytest.mark.asyncio
async def test_redis_pubsub_idle_polls_do_not_trigger_resubscribe() -> None:
    received = asyncio.Event()
    pubsub = StubPubSub(
        responses=[
            None,
            None,
            {
                "type": "pmessage",
                "channel": "tourism:events:support:one",
                "data": "after-idle",
            },
        ]
    )
    client = StubRedisClient([pubsub])
    backend = RedisCoordinationBackend(
        url="redis://unused",
        socket_timeout_seconds=0.1,
    )
    backend.client = client  # type: ignore[assignment]

    async def handler(topic: str, payload: str) -> None:
        assert (topic, payload) == ("support:one", "after-idle")
        received.set()

    await backend.subscribe("support:*", handler)
    await asyncio.wait_for(received.wait(), timeout=1)
    assert backend.pubsub_healthy is True
    assert client.pubsubs == []
    await backend.close()


def _runtime_settings(*, required: bool = False) -> Settings:
    return Settings(
        app_env="test",
        redis_url="redis://unused:6379/0",
        redis_coordination_enabled=True,
        redis_required=required,
        trusted_hosts=["testserver"],
        cors_origins=["https://client.example"],
        rate_limit_mutation_requests=1,
        crowd_publish_interval_seconds=3600,
        queue_publish_interval_seconds=3600,
        log_level="CRITICAL",
    )


def _add_probe_route(application: FastAPI) -> None:
    @application.post("/api/v1/runtime-probe")
    async def runtime_probe(request: Request) -> dict[str, bool]:
        async with request.app.state.coordination_locks.hold("probe"):
            return {"ok": True}

    @application.get("/api/v1/runtime-boom")
    async def runtime_boom() -> None:
        raise RuntimeError("expected test failure")


def test_registration_uses_the_stricter_auth_rate_limit_bucket() -> None:
    settings = _runtime_settings()
    application = FastAPI()
    application.state.settings = settings
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": [],
            "query_string": b"",
            "app": application,
        }
    )

    assert RateLimitMiddleware._selected_limit(request) == (
        "auth",
        settings.rate_limit_auth_requests,
    )


def test_auth_rate_limit_cannot_be_bypassed_with_a_bearer_subject() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret_key="test-auth-rate-limit-secret-123456789",
        rate_limit_auth_requests=1,
        log_level="CRITICAL",
    )
    backend = TrackingBackend()
    application = FastAPI()
    application.state.settings = settings
    application.state.rate_limit_backend = backend
    application.state.local_coordination = LocalCoordinationBackend()
    application.add_middleware(RateLimitMiddleware)

    @application.post("/api/v1/auth/register")
    async def registration_probe() -> dict[str, bool]:
        return {"ok": True}

    access_token, _ = create_access_token(uuid4(), ["tourist"], settings)
    with TestClient(application) as client:
        first = client.post("/api/v1/auth/register")
        bypass_attempt = client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert first.status_code == 200
    assert bypass_attempt.status_code == 429
    assert bypass_attempt.json()["error"]["code"] == "RATE_LIMITED"
    assert len(backend.rate_requests) == 2
    assert backend.rate_requests[0]["key"] == backend.rate_requests[1]["key"]


def test_full_mode_lifecycle_rate_limit_security_and_host_guard() -> None:
    backend = TrackingBackend()
    application = create_app(_runtime_settings(), redis_backend=backend)
    _add_probe_route(application)

    origin = {"Origin": "https://client.example"}
    with TestClient(application, raise_server_exceptions=False) as client:
        health = client.get(
            "/health",
            headers={"X-Request-ID": "accepted-request-id"},
        )
        assert health.status_code == 200
        assert health.headers["X-Request-ID"] == "accepted-request-id"
        assert health.headers["X-Content-Type-Options"] == "nosniff"

        assert client.post("/api/v1/runtime-probe", headers=origin).status_code == 200
        limited = client.post("/api/v1/runtime-probe", headers=origin)
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMITED"
        assert limited.headers["Retry-After"]
        assert limited.headers["Access-Control-Allow-Origin"] == origin["Origin"]
        assert limited.headers["X-Content-Type-Options"] == "nosniff"

        rejected_host = client.get(
            "/health",
            headers={"Host": "evil.example", **origin},
        )
        assert rejected_host.status_code == 400
        assert rejected_host.headers["X-Request-ID"]
        assert rejected_host.headers["Access-Control-Allow-Origin"] == origin["Origin"]
        assert rejected_host.headers["X-Content-Type-Options"] == "nosniff"

        failed = client.get("/api/v1/runtime-boom", headers=origin)
        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert failed.headers["Access-Control-Allow-Origin"] == origin["Origin"]
        assert failed.headers["X-Content-Type-Options"] == "nosniff"

    assert backend.calls.count("subscribe") == 3
    assert {"start", "rate_limit", "claim", "release_claim", "close"}.issubset(backend.calls)


def test_optional_startup_falls_back_but_required_startup_fails() -> None:
    optional_backend = TrackingBackend(fail_start=True)
    optional_app = create_app(_runtime_settings(), redis_backend=optional_backend)
    with TestClient(optional_app) as client:
        assert client.get("/health").status_code == 200
        assert optional_app.state.coordination_mode == "local"

    required_backend = TrackingBackend(fail_start=True)
    required_app = create_app(
        _runtime_settings(required=True),
        redis_backend=required_backend,
    )
    with pytest.raises(CoordinationUnavailableError), TestClient(required_app):
        pass


def test_required_runtime_rate_backend_failure_returns_503() -> None:
    backend = TrackingBackend(fail_operations={"rate_limit"})
    application = create_app(
        _runtime_settings(required=True),
        redis_backend=backend,
    )
    _add_probe_route(application)

    with TestClient(application) as client:
        response = client.post("/api/v1/runtime-probe")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "COORDINATION_UNAVAILABLE"


def test_required_health_reports_disconnected_pubsub() -> None:
    backend = TrackingBackend()
    backend.pubsub_is_healthy = False
    application = create_app(
        _runtime_settings(required=True),
        redis_backend=backend,
    )
    with TestClient(application) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "COORDINATION_UNAVAILABLE"


def test_forwarded_ip_requires_a_trusted_direct_proxy() -> None:
    untrusted = TrackingBackend()
    untrusted_app = create_app(_runtime_settings(), redis_backend=untrusted)
    _add_probe_route(untrusted_app)
    with TestClient(untrusted_app, client=("198.51.100.20", 50000)) as client:
        assert (
            client.post(
                "/api/v1/runtime-probe",
                headers={"X-Forwarded-For": "203.0.113.9"},
            ).status_code
            == 200
        )
    assert untrusted.rate_requests[-1]["key"] == "mutation:198.51.100.20"

    trusted = TrackingBackend()
    trusted_settings = _runtime_settings().model_copy(
        update={"trusted_proxy_networks": ["10.0.0.0/8"]}
    )
    trusted_app = create_app(trusted_settings, redis_backend=trusted)
    _add_probe_route(trusted_app)
    with TestClient(trusted_app, client=("10.1.2.3", 50000)) as client:
        assert (
            client.post(
                "/api/v1/runtime-probe",
                headers={"X-Forwarded-For": "203.0.113.9, 10.2.3.4"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/runtime-probe",
                headers={"X-Forwarded-For": "not-an-ip"},
            ).status_code
            == 200
        )
    assert trusted.rate_requests[-2]["key"] == "mutation:203.0.113.9"
    assert trusted.rate_requests[-1]["key"] == "mutation:10.1.2.3"


def test_invalid_request_id_is_replaced() -> None:
    application = create_app(
        Settings(
            app_env="test",
            trusted_hosts=["testserver"],
            log_level="CRITICAL",
        )
    )
    with TestClient(application) as client:
        response = client.get("/health", headers={"X-Request-ID": "bad id\r\nvalue"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad id\r\nvalue"
    assert len(response.headers["X-Request-ID"]) == 32

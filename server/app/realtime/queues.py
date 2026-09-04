"""Queue-specific single-use tickets, fan-out hub, and one lifespan publisher."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.coordination import (
    CoordinationBackend,
    CoordinationUnavailableError,
    LocalCoordinationBackend,
    coordination_payload,
)
from app.schemas.marketplace import QueueWebSocketEnvelope
from app.services.queues import advance_queue_tick, queue_envelope
from app.services.reservations import expire_reservation_holds

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueueTicket:
    user_id: UUID
    queue_id: UUID
    expires_at: datetime


class QueueTicketStore:
    """Atomic one-time tickets backed by Redis when full mode is enabled."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        backend: CoordinationBackend | None = None,
        fallback: LocalCoordinationBackend | None = None,
        allow_degraded: bool = True,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.fallback = fallback or LocalCoordinationBackend()
        self.backend = backend or self.fallback
        self.allow_degraded = allow_degraded
        self._lock = asyncio.Lock()
        self._local_only: dict[str, datetime] = {}

    def configure_backend(self, backend: CoordinationBackend) -> None:
        self.backend = backend

    async def issue(self, *, user_id: UUID, queue_id: UUID) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        self._local_only = {key: expiry for key, expiry in self._local_only.items() if expiry > now}
        payload = coordination_payload(
            {
                "user_id": user_id,
                "queue_id": queue_id,
                "expires_at": expires_at,
            }
        )
        for _ in range(3):
            token = secrets.token_urlsafe(32)
            key = f"queue:{sha256(token.encode()).hexdigest()}"
            try:
                stored = await self.backend.ticket_put(
                    key=key,
                    payload=payload,
                    ttl_seconds=self.ttl_seconds,
                )
            except CoordinationUnavailableError:
                if not self.allow_degraded:
                    raise
                logger.warning("Queue ticket issue degraded to local")
                stored = await self.fallback.ticket_put(
                    key=key,
                    payload=payload,
                    ttl_seconds=self.ttl_seconds,
                )
                if stored:
                    self._local_only[key] = expires_at
                    return token, expires_at
                continue
            if not stored:
                continue
            return token, expires_at
        raise RuntimeError("Unable to allocate a unique queue WebSocket ticket")

    async def consume(
        self,
        *,
        token: str,
        queue_id: UUID,
    ) -> QueueTicket | None:
        """Atomically burn before validation, including wrong-channel attempts."""

        key = f"queue:{sha256(token.encode()).hexdigest()}"
        async with self._lock:
            now = datetime.now(UTC)
            self._local_only = {
                found_key: expiry for found_key, expiry in self._local_only.items() if expiry > now
            }
            try:
                raw = await self.backend.ticket_take(key)
            except CoordinationUnavailableError:
                if not self.allow_degraded:
                    raise
                logger.warning("Queue ticket consume degraded to local")
                raw = await self.fallback.ticket_take(key)
            else:
                if raw is None and self.allow_degraded and key in self._local_only:
                    raw = await self.fallback.ticket_take(key)
            self._local_only.pop(key, None)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            ticket = QueueTicket(
                user_id=UUID(value["user_id"]),
                queue_id=UUID(value["queue_id"]),
                expires_at=datetime.fromisoformat(value["expires_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if ticket.queue_id != queue_id or ticket.expires_at <= datetime.now(UTC):
            return None
        return ticket


class QueueConnectionHub:
    """Latest-value queue fan-out with optional cross-worker Redis pub/sub."""

    def __init__(
        self,
        *,
        backend: CoordinationBackend | None = None,
        allow_degraded: bool = True,
    ) -> None:
        self._queues: dict[
            UUID,
            dict[str, asyncio.Queue[QueueWebSocketEnvelope]],
        ] = {}
        self.backend = backend
        self.allow_degraded = allow_degraded
        self.origin = uuid4().hex

    def configure_backend(self, backend: CoordinationBackend) -> None:
        self.backend = backend

    async def start(self) -> None:
        if self.backend is not None and self.backend.distributed:
            await self.backend.subscribe("queue:*", self._receive)

    def register(
        self,
        queue_id: UUID,
    ) -> tuple[str, asyncio.Queue[QueueWebSocketEnvelope]]:
        connection_id = uuid4().hex
        queue: asyncio.Queue[QueueWebSocketEnvelope] = asyncio.Queue(maxsize=1)
        self._queues.setdefault(queue_id, {})[connection_id] = queue
        return connection_id, queue

    def unregister(self, queue_id: UUID, connection_id: str) -> None:
        connections = self._queues.get(queue_id)
        if connections is None:
            return
        connections.pop(connection_id, None)
        if not connections:
            self._queues.pop(queue_id, None)

    async def broadcast(
        self,
        queue_id: UUID,
        envelope: QueueWebSocketEnvelope,
    ) -> None:
        await self._broadcast_local(queue_id, envelope)
        if self.backend is None or not self.backend.distributed:
            return
        payload = coordination_payload(
            {
                "origin": self.origin,
                "data": envelope.model_dump(mode="json"),
            }
        )
        try:
            await self.backend.publish(f"queue:{queue_id}", payload)
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning("Queue broadcast degraded to local")

    async def _broadcast_local(
        self,
        queue_id: UUID,
        envelope: QueueWebSocketEnvelope,
    ) -> None:
        for queue in tuple(self._queues.get(queue_id, {}).values()):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

    async def _receive(self, topic: str, payload: str) -> None:
        try:
            queue_id = UUID(topic.removeprefix("queue:"))
            decoded = json.loads(payload)
            if decoded.get("origin") == self.origin:
                return
            envelope = QueueWebSocketEnvelope.model_validate(decoded["data"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring invalid queue pub/sub payload")
            return
        await self._broadcast_local(queue_id, envelope)

    @property
    def connection_count(self) -> int:
        return sum(len(connections) for connections in self._queues.values())


class QueuePublisher:
    """One queue simulation producer per FastAPI lifespan."""

    def __init__(
        self,
        *,
        hub: QueueConnectionHub,
        session_factory_provider: Callable[[], async_sessionmaker[AsyncSession]],
        interval_seconds: float,
        leader_backend: CoordinationBackend | None = None,
        allow_degraded: bool = True,
    ) -> None:
        self.hub = hub
        self.session_factory_provider = session_factory_provider
        self.interval_seconds = interval_seconds
        self.leader_backend = leader_backend
        self.allow_degraded = allow_degraded
        self._task: asyncio.Task[None] | None = None

    def configure_leader_backend(self, backend: CoordinationBackend) -> None:
        self.leader_backend = backend

    async def _is_tick_leader(self) -> bool:
        backend = self.leader_backend
        if backend is None or not backend.distributed:
            return True
        try:
            decision = await backend.rate_limit(
                key="publisher:queue",
                limit=1,
                window_seconds=max(ceil(self.interval_seconds), 1),
            )
            return decision.allowed
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning("Queue publisher leadership degraded to local")
            return True

    async def publish_once(self) -> list[QueueWebSocketEnvelope]:
        if not await self._is_tick_leader():
            return []
        factory = self.session_factory_provider()
        async with factory() as session:
            await expire_reservation_holds(session)
            await session.commit()
            responses = await advance_queue_tick(session)
        envelopes = [queue_envelope(response) for response in responses]
        for response, envelope in zip(responses, envelopes, strict=True):
            await self.hub.broadcast(UUID(response.id), envelope)
        return envelopes

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(),
                name="simulated-queue-publisher",
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            try:
                await self.publish_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Simulated queue publisher tick failed")

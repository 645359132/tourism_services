"""Queue-specific single-use tickets, fan-out hub, and one lifespan publisher."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    """Process-local atomic one-time tickets; Redis is the multi-worker boundary."""

    def __init__(self, *, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._tickets: dict[str, QueueTicket] = {}
        self._lock = asyncio.Lock()

    async def issue(self, *, user_id: UUID, queue_id: UUID) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        token = secrets.token_urlsafe(32)
        async with self._lock:
            self._purge_expired(now)
            self._tickets[sha256(token.encode()).hexdigest()] = QueueTicket(
                user_id,
                queue_id,
                expires_at,
            )
        return token, expires_at

    async def consume(
        self,
        *,
        token: str,
        queue_id: UUID,
    ) -> QueueTicket | None:
        """Pop before validation so wrong-channel attempts also burn the ticket."""

        now = datetime.now(UTC)
        async with self._lock:
            self._purge_expired(now)
            ticket = self._tickets.pop(sha256(token.encode()).hexdigest(), None)
        if ticket is None or ticket.queue_id != queue_id or ticket.expires_at <= now:
            return None
        return ticket

    def _purge_expired(self, now: datetime) -> None:
        expired = [token for token, ticket in self._tickets.items() if ticket.expires_at <= now]
        for token in expired:
            self._tickets.pop(token, None)

    @property
    def pending_count(self) -> int:
        return len(self._tickets)


class QueueConnectionHub:
    """Latest-value queue fan-out partitioned by queue entry id."""

    def __init__(self) -> None:
        self._queues: dict[
            UUID,
            dict[str, asyncio.Queue[QueueWebSocketEnvelope]],
        ] = {}

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
        for queue in tuple(self._queues.get(queue_id, {}).values()):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

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
    ) -> None:
        self.hub = hub
        self.session_factory_provider = session_factory_provider
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def publish_once(self) -> list[QueueWebSocketEnvelope]:
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

"""Support-specific one-time tickets and persisted-message fan-out."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from app.schemas.engagement import SupportWebSocketEnvelope


@dataclass(frozen=True, slots=True)
class SupportTicket:
    user_id: UUID
    conversation_id: UUID
    expires_at: datetime


class SupportTicketStore:
    """Atomic one-use support tickets isolated from queue ticket scope."""

    def __init__(self, *, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._tickets: dict[str, SupportTicket] = {}
        self._lock = asyncio.Lock()

    async def issue(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        async with self._lock:
            self._purge(datetime.now(UTC))
            self._tickets[sha256(token.encode()).hexdigest()] = SupportTicket(
                user_id,
                conversation_id,
                expires_at,
            )
        return token, expires_at

    async def consume(
        self,
        *,
        token: str,
        conversation_id: UUID,
    ) -> SupportTicket | None:
        now = datetime.now(UTC)
        async with self._lock:
            self._purge(now)
            grant = self._tickets.pop(sha256(token.encode()).hexdigest(), None)
        if grant is None or grant.conversation_id != conversation_id or grant.expires_at <= now:
            return None
        return grant

    def _purge(self, now: datetime) -> None:
        expired = [digest for digest, ticket in self._tickets.items() if ticket.expires_at <= now]
        for digest in expired:
            self._tickets.pop(digest, None)


class SupportConnectionHub:
    """Latest-message fan-out partitioned by persisted conversation id."""

    def __init__(self) -> None:
        self._queues: dict[
            UUID,
            dict[str, asyncio.Queue[SupportWebSocketEnvelope]],
        ] = {}

    def register(
        self,
        conversation_id: UUID,
    ) -> tuple[str, asyncio.Queue[SupportWebSocketEnvelope]]:
        connection_id = uuid4().hex
        queue: asyncio.Queue[SupportWebSocketEnvelope] = asyncio.Queue(maxsize=10)
        self._queues.setdefault(conversation_id, {})[connection_id] = queue
        return connection_id, queue

    def unregister(self, conversation_id: UUID, connection_id: str) -> None:
        connections = self._queues.get(conversation_id)
        if connections is None:
            return
        connections.pop(connection_id, None)
        if not connections:
            self._queues.pop(conversation_id, None)

    async def broadcast(
        self,
        conversation_id: UUID,
        envelope: SupportWebSocketEnvelope,
    ) -> None:
        for queue in tuple(self._queues.get(conversation_id, {}).values()):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

    @property
    def connection_count(self) -> int:
        return sum(len(connections) for connections in self._queues.values())

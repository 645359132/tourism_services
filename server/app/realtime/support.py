"""Support-specific one-time tickets and persisted-message fan-out."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from app.core.coordination import (
    CoordinationBackend,
    CoordinationUnavailableError,
    LocalCoordinationBackend,
    coordination_payload,
)
from app.schemas.engagement import SupportWebSocketEnvelope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SupportTicket:
    user_id: UUID
    conversation_id: UUID
    expires_at: datetime


class SupportTicketStore:
    """Atomic one-use support tickets isolated from queue ticket scope."""

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

    async def issue(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        self._local_only = {
            key: expiry for key, expiry in self._local_only.items() if expiry > datetime.now(UTC)
        }
        payload = coordination_payload(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "expires_at": expires_at,
            }
        )
        for _ in range(3):
            token = secrets.token_urlsafe(32)
            key = f"support:{sha256(token.encode()).hexdigest()}"
            try:
                stored = await self.backend.ticket_put(
                    key=key,
                    payload=payload,
                    ttl_seconds=self.ttl_seconds,
                )
            except CoordinationUnavailableError:
                if not self.allow_degraded:
                    raise
                logger.warning("Support ticket issue degraded to local")
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
        raise RuntimeError("Unable to allocate a unique support WebSocket ticket")

    async def consume(
        self,
        *,
        token: str,
        conversation_id: UUID,
    ) -> SupportTicket | None:
        key = f"support:{sha256(token.encode()).hexdigest()}"
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
                logger.warning("Support ticket consume degraded to local")
                raw = await self.fallback.ticket_take(key)
            else:
                if raw is None and self.allow_degraded and key in self._local_only:
                    raw = await self.fallback.ticket_take(key)
            self._local_only.pop(key, None)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            grant = SupportTicket(
                user_id=UUID(value["user_id"]),
                conversation_id=UUID(value["conversation_id"]),
                expires_at=datetime.fromisoformat(value["expires_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if grant.conversation_id != conversation_id or grant.expires_at <= datetime.now(UTC):
            return None
        return grant


class SupportConnectionHub:
    """Conversation fan-out with optional cross-worker Redis pub/sub."""

    def __init__(
        self,
        *,
        backend: CoordinationBackend | None = None,
        allow_degraded: bool = True,
    ) -> None:
        self._queues: dict[
            UUID,
            dict[str, asyncio.Queue[SupportWebSocketEnvelope]],
        ] = {}
        self.backend = backend
        self.allow_degraded = allow_degraded
        self.origin = uuid4().hex

    def configure_backend(self, backend: CoordinationBackend) -> None:
        self.backend = backend

    async def start(self) -> None:
        if self.backend is not None and self.backend.distributed:
            await self.backend.subscribe("support:*", self._receive)

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
        await self._broadcast_local(conversation_id, envelope)
        if self.backend is None or not self.backend.distributed:
            return
        payload = coordination_payload(
            {
                "origin": self.origin,
                "data": envelope.model_dump(mode="json"),
            }
        )
        try:
            await self.backend.publish(f"support:{conversation_id}", payload)
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning("Support broadcast degraded to local")

    async def _broadcast_local(
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

    async def _receive(self, topic: str, payload: str) -> None:
        try:
            conversation_id = UUID(topic.removeprefix("support:"))
            decoded = json.loads(payload)
            if decoded.get("origin") == self.origin:
                return
            envelope = SupportWebSocketEnvelope.model_validate(decoded["data"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring invalid support pub/sub payload")
            return
        await self._broadcast_local(conversation_id, envelope)

    @property
    def connection_count(self) -> int:
        return sum(len(connections) for connections in self._queues.values())

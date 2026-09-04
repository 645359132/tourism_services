"""Non-blocking in-process crowd fan-out with a future Redis boundary."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from math import ceil
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.coordination import (
    CoordinationBackend,
    CoordinationUnavailableError,
    coordination_payload,
)
from app.schemas.guide import CrowdWebSocketEnvelope
from app.services.guide import crowd_envelope, simulate_crowd_tick

logger = logging.getLogger(__name__)


class ConnectionHub:
    """Latest-value hub with optional cross-worker Redis pub/sub."""

    def __init__(
        self,
        *,
        backend: CoordinationBackend | None = None,
        allow_degraded: bool = True,
    ) -> None:
        self._queues: dict[str, asyncio.Queue[CrowdWebSocketEnvelope]] = {}
        self.backend = backend
        self.allow_degraded = allow_degraded
        self.origin = uuid4().hex

    def configure_backend(self, backend: CoordinationBackend) -> None:
        self.backend = backend

    async def start(self) -> None:
        if self.backend is not None and self.backend.distributed:
            await self.backend.subscribe("crowd", self._receive)

    def register(self) -> tuple[str, asyncio.Queue[CrowdWebSocketEnvelope]]:
        connection_id = uuid4().hex
        queue: asyncio.Queue[CrowdWebSocketEnvelope] = asyncio.Queue(maxsize=1)
        self._queues[connection_id] = queue
        return connection_id, queue

    def unregister(self, connection_id: str) -> None:
        self._queues.pop(connection_id, None)

    async def broadcast(self, envelope: CrowdWebSocketEnvelope) -> None:
        await self._broadcast_local(envelope)
        if self.backend is None or not self.backend.distributed:
            return
        payload = coordination_payload(
            {
                "origin": self.origin,
                "data": envelope.model_dump(mode="json"),
            }
        )
        try:
            await self.backend.publish("crowd", payload)
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning("Crowd broadcast degraded to local")

    async def _broadcast_local(self, envelope: CrowdWebSocketEnvelope) -> None:
        for queue in tuple(self._queues.values()):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

    async def _receive(self, topic: str, payload: str) -> None:
        if topic != "crowd":
            return
        try:
            decoded = json.loads(payload)
            if decoded.get("origin") == self.origin:
                return
            envelope = CrowdWebSocketEnvelope.model_validate(decoded["data"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring invalid crowd pub/sub payload")
            return
        await self._broadcast_local(envelope)

    @property
    def connection_count(self) -> int:
        return len(self._queues)


class CrowdPublisher:
    """One producer per app process; all WS connections share its sequences."""

    def __init__(
        self,
        *,
        hub: ConnectionHub,
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
                key="publisher:crowd",
                limit=1,
                window_seconds=max(ceil(self.interval_seconds), 1),
            )
            return decision.allowed
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning("Crowd publisher leadership degraded to local")
            return True

    async def publish_once(self) -> CrowdWebSocketEnvelope | None:
        if not await self._is_tick_leader():
            return None
        factory = self.session_factory_provider()
        async with factory() as session:
            response = await simulate_crowd_tick(session)
        envelope = crowd_envelope(response)
        await self.hub.broadcast(envelope)
        return envelope

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="simulated-crowd-publisher")

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
                logger.exception("Simulated crowd publisher tick failed")

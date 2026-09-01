"""Non-blocking in-process crowd fan-out with a future Redis boundary."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.guide import CrowdWebSocketEnvelope
from app.services.guide import crowd_envelope, simulate_crowd_tick

logger = logging.getLogger(__name__)


class RedisCrowdHubAdapter(Protocol):
    """Future multi-worker broadcast interface; not implemented by this MVP."""

    async def broadcast(self, envelope: CrowdWebSocketEnvelope) -> None: ...


class ConnectionHub:
    """Single-worker latest-value hub; slow consumers never block publishers."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[CrowdWebSocketEnvelope]] = {}

    def register(self) -> tuple[str, asyncio.Queue[CrowdWebSocketEnvelope]]:
        connection_id = uuid4().hex
        queue: asyncio.Queue[CrowdWebSocketEnvelope] = asyncio.Queue(maxsize=1)
        self._queues[connection_id] = queue
        return connection_id, queue

    def unregister(self, connection_id: str) -> None:
        self._queues.pop(connection_id, None)

    async def broadcast(self, envelope: CrowdWebSocketEnvelope) -> None:
        for queue in tuple(self._queues.values()):
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(envelope)

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
    ) -> None:
        self.hub = hub
        self.session_factory_provider = session_factory_provider
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def publish_once(self) -> CrowdWebSocketEnvelope:
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

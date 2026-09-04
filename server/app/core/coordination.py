"""Optional distributed coordination with a complete in-process fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

MessageHandler = Callable[[str, str], Awaitable[None]]
ModelT = TypeVar("ModelT", bound=BaseModel)
logger = logging.getLogger(__name__)


class CoordinationUnavailableError(RuntimeError):
    """Raised when a required distributed backend cannot start."""


class CoordinationBusyError(RuntimeError):
    """Raised when a short-lived coordination lock cannot be acquired."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Coordination lock is busy: {key}")
        self.key = key


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class CoordinationBackend(ABC):
    """Coordination primitives; durable business state always remains in SQL."""

    distributed = False

    @property
    def pubsub_healthy(self) -> bool:
        return True

    async def start(self) -> None:
        """Initialize network resources when required."""
        return None

    async def close(self) -> None:
        """Release all backend resources."""
        return None

    @abstractmethod
    async def rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision: ...

    @abstractmethod
    async def cache_get(self, key: str) -> str | None: ...

    @abstractmethod
    async def cache_set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def claim(
        self,
        *,
        key: str,
        owner: str,
        ttl_seconds: int,
    ) -> bool: ...

    @abstractmethod
    async def release_claim(self, *, key: str, owner: str) -> None: ...

    @abstractmethod
    async def ticket_put(
        self,
        *,
        key: str,
        payload: str,
        ttl_seconds: int,
    ) -> bool: ...

    @abstractmethod
    async def ticket_take(self, key: str) -> str | None: ...

    @abstractmethod
    async def publish(self, topic: str, payload: str) -> None: ...

    @abstractmethod
    async def subscribe(self, pattern: str, handler: MessageHandler) -> None: ...

    @asynccontextmanager
    async def lock(
        self,
        *,
        key: str,
        ttl_seconds: int,
        wait_seconds: float,
    ) -> AsyncIterator[bool]:
        owner = secrets.token_urlsafe(18)
        deadline = monotonic() + max(wait_seconds, 0)
        acquired = False
        while True:
            acquired = await self.claim(
                key=f"lock:{key}",
                owner=owner,
                ttl_seconds=ttl_seconds,
            )
            if acquired or monotonic() >= deadline:
                break
            await asyncio.sleep(0.02)
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    await self.release_claim(key=f"lock:{key}", owner=owner)
                except CoordinationUnavailableError:
                    # SQL is authoritative. A failed unlock must not turn a
                    # committed business operation into an HTTP failure; TTL
                    # expiry bounds the orphaned advisory lock.
                    logger.warning("Coordination lock release failed", extra={"lock_key": key})


class LocalCoordinationBackend(CoordinationBackend):
    """Bounded process-local implementation used in zero-service mode."""

    def __init__(self, *, max_entries: int = 10_000) -> None:
        self.max_entries = max_entries
        self._mutex = asyncio.Lock()
        self._rates: dict[str, tuple[float, int]] = {}
        self._cache: dict[str, tuple[float, str]] = {}
        self._claims: dict[str, tuple[float, str]] = {}
        self._tickets: dict[str, tuple[float, str]] = {}

    def _purge(self, now: float) -> None:
        for storage in (self._cache, self._claims, self._tickets):
            expired = [key for key, (expires, _) in storage.items() if expires <= now]
            for key in expired:
                storage.pop(key, None)
        expired_rates = [key for key, (started, _) in self._rates.items() if started <= now]
        for key in expired_rates:
            self._rates.pop(key, None)

    def _trim(self, storage: dict[str, Any]) -> None:
        overflow = len(storage) - self.max_entries
        for key in list(storage)[: max(overflow, 0)]:
            storage.pop(key, None)

    async def rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        now = monotonic()
        async with self._mutex:
            self._purge(now)
            expires_at, count = self._rates.get(
                key,
                (now + window_seconds, 0),
            )
            count += 1
            self._rates[key] = (expires_at, count)
            self._trim(self._rates)
        return RateLimitDecision(
            allowed=count <= limit,
            remaining=max(limit - count, 0),
            retry_after_seconds=max(int(expires_at - now + 0.999), 1),
        )

    async def cache_get(self, key: str) -> str | None:
        now = monotonic()
        async with self._mutex:
            self._purge(now)
            found = self._cache.get(key)
            return None if found is None else found[1]

    async def cache_set(self, key: str, value: str, ttl_seconds: int) -> None:
        async with self._mutex:
            self._cache[key] = (monotonic() + ttl_seconds, value)
            self._trim(self._cache)

    async def claim(
        self,
        *,
        key: str,
        owner: str,
        ttl_seconds: int,
    ) -> bool:
        now = monotonic()
        async with self._mutex:
            self._purge(now)
            if key in self._claims:
                return False
            self._claims[key] = (now + ttl_seconds, owner)
            self._trim(self._claims)
            return True

    async def release_claim(self, *, key: str, owner: str) -> None:
        async with self._mutex:
            found = self._claims.get(key)
            if found is not None and found[1] == owner:
                self._claims.pop(key, None)

    async def ticket_put(
        self,
        *,
        key: str,
        payload: str,
        ttl_seconds: int,
    ) -> bool:
        now = monotonic()
        async with self._mutex:
            self._purge(now)
            if key in self._tickets:
                return False
            self._tickets[key] = (now + ttl_seconds, payload)
            self._trim(self._tickets)
            return True

    async def ticket_take(self, key: str) -> str | None:
        now = monotonic()
        async with self._mutex:
            self._purge(now)
            found = self._tickets.pop(key, None)
            return None if found is None else found[1]

    async def publish(self, topic: str, payload: str) -> None:
        del topic, payload

    async def subscribe(self, pattern: str, handler: MessageHandler) -> None:
        del pattern, handler


class ReferenceCache:
    """Short-lived cache for stable public reference responses.

    Values are always populated from SQL and validated back into the declared
    response model. Redis failures transparently use the bounded local cache.
    """

    def __init__(
        self,
        *,
        backend: CoordinationBackend,
        fallback: LocalCoordinationBackend,
        ttl_seconds: int,
        allow_degraded: bool = True,
    ) -> None:
        self.backend = backend
        self.fallback = fallback
        self.ttl_seconds = ttl_seconds
        self.allow_degraded = allow_degraded

    def configure_backend(self, backend: CoordinationBackend) -> None:
        self.backend = backend

    async def get_or_load(
        self,
        *,
        key: str,
        model: type[ModelT],
        loader: Callable[[], Awaitable[ModelT]],
    ) -> ModelT:
        cached = await self._get(key)
        if cached is not None:
            try:
                return model.model_validate_json(cached)
            except ValidationError:
                logger.warning(
                    "Discarding invalid coordination cache value",
                    extra={"cache_key": key},
                )

        value = await loader()
        encoded = value.model_dump_json()
        await self._set(key, encoded)
        return value

    async def _get(self, key: str) -> str | None:
        try:
            return await self.backend.cache_get(key)
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning(
                "Reference cache read degraded to local",
                extra={"cache_key": key},
            )
            return await self.fallback.cache_get(key)

    async def _set(self, key: str, value: str) -> None:
        try:
            await self.backend.cache_set(key, value, self.ttl_seconds)
        except CoordinationUnavailableError:
            if not self.allow_degraded:
                raise
            logger.warning(
                "Reference cache write degraded to local",
                extra={"cache_key": key},
            )
            await self.fallback.cache_set(key, value, self.ttl_seconds)
            return
        if self.backend is not self.fallback:
            # A local mirror keeps the current worker useful during a later
            # Redis outage without making the cache authoritative.
            await self.fallback.cache_set(key, value, self.ttl_seconds)


class CoordinationLockManager:
    """Acquire ordered advisory locks with local degradation.

    SQL constraints and conditional updates remain the correctness boundary;
    these locks reduce duplicate work and cross-worker inventory contention.
    """

    def __init__(
        self,
        *,
        backend: CoordinationBackend,
        fallback: LocalCoordinationBackend,
        ttl_seconds: int,
        wait_seconds: float,
        allow_degraded: bool = True,
    ) -> None:
        self.backend = backend
        self.fallback = fallback
        self.ttl_seconds = ttl_seconds
        self.wait_seconds = wait_seconds
        self.allow_degraded = allow_degraded

    def configure_backend(self, backend: CoordinationBackend) -> None:
        self.backend = backend

    @asynccontextmanager
    async def hold(self, *keys: str) -> AsyncIterator[None]:
        ordered = sorted(set(keys))
        if not ordered:
            yield
            return

        stack = AsyncExitStack()
        try:
            try:
                await self._acquire(stack, self.backend, ordered)
            except CoordinationUnavailableError:
                if not self.allow_degraded:
                    raise
                await stack.aclose()
                stack = AsyncExitStack()
                logger.warning("Coordination locks degraded to local")
                await self._acquire(stack, self.fallback, ordered)
            yield
        finally:
            await stack.aclose()

    async def _acquire(
        self,
        stack: AsyncExitStack,
        backend: CoordinationBackend,
        keys: Iterable[str],
    ) -> None:
        deadline = monotonic() + max(self.wait_seconds, 0)
        for key in keys:
            remaining = max(deadline - monotonic(), 0)
            acquired = await stack.enter_async_context(
                backend.lock(
                    key=key,
                    ttl_seconds=self.ttl_seconds,
                    wait_seconds=remaining,
                )
            )
            if not acquired:
                raise CoordinationBusyError(key)


def coordination_key(namespace: str, *parts: object) -> str:
    """Return a bounded, non-sensitive key for advisory coordination."""

    material = "\x1f".join(str(part) for part in parts)
    digest = sha256(material.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


class RedisCoordinationBackend(CoordinationBackend):
    """Redis-backed coordination used only when explicitly enabled."""

    distributed = True
    _RECONNECT_INITIAL_SECONDS = 0.05
    _RECONNECT_MAX_SECONDS = 2.0
    _PUBSUB_POLL_SECONDS = 1.0
    _RATE_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""
    _TAKE_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
"""
    _RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

    def __init__(
        self,
        *,
        url: str,
        prefix: str = "tourism",
        socket_timeout_seconds: float = 2.0,
    ) -> None:
        self.url = url
        self.prefix = prefix.strip(":")
        self.socket_timeout_seconds = socket_timeout_seconds
        self.client: Redis | None = None
        self._listener_tasks: list[asyncio.Task[None]] = []
        self._pubsubs: list[Any] = []
        self._subscription_health: dict[int, bool] = {}
        self._next_subscription_id = 0
        self._closing = False

    def _key(self, namespace: str, key: str) -> str:
        return f"{self.prefix}:{namespace}:{key}"

    def _require_client(self) -> Redis:
        if self.client is None:
            raise CoordinationUnavailableError("Redis coordination is not started")
        return self.client

    @property
    def pubsub_healthy(self) -> bool:
        return all(self._subscription_health.values())

    async def start(self) -> None:
        self._closing = False
        client: Redis | None = None
        try:
            client = Redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=self.socket_timeout_seconds,
                socket_timeout=self.socket_timeout_seconds,
                health_check_interval=30,
            )
            await client.ping()
            self.client = client
        except (RedisError, OSError, TimeoutError) as exc:
            if client is not None:
                with suppress(RedisError, OSError, TimeoutError):
                    await client.aclose()
            raise CoordinationUnavailableError("Redis coordination startup failed") from exc

    async def close(self) -> None:
        self._closing = True
        for task in self._listener_tasks:
            task.cancel()
        for task in self._listener_tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._listener_tasks.clear()
        for pubsub in self._pubsubs:
            with suppress(RedisError, OSError, TimeoutError):
                await pubsub.aclose()
        self._pubsubs.clear()
        self._subscription_health.clear()
        if self.client is not None:
            with suppress(RedisError, OSError, TimeoutError):
                await self.client.aclose()
        self.client = None

    async def rate_limit(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        client = self._require_client()
        try:
            result = await client.eval(
                self._RATE_SCRIPT,
                1,
                self._key("rate", key),
                window_seconds,
            )
            count, ttl = int(result[0]), max(int(result[1]), 1)
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis rate limit failed") from exc
        return RateLimitDecision(
            allowed=count <= limit,
            remaining=max(limit - count, 0),
            retry_after_seconds=ttl,
        )

    async def cache_get(self, key: str) -> str | None:
        try:
            return await self._require_client().get(self._key("cache", key))
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis cache read failed") from exc

    async def cache_set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._require_client().set(
                self._key("cache", key),
                value,
                ex=ttl_seconds,
            )
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis cache write failed") from exc

    async def claim(
        self,
        *,
        key: str,
        owner: str,
        ttl_seconds: int,
    ) -> bool:
        try:
            result = await self._require_client().set(
                self._key("claim", key),
                owner,
                ex=ttl_seconds,
                nx=True,
            )
            return bool(result)
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis claim failed") from exc

    async def release_claim(self, *, key: str, owner: str) -> None:
        try:
            await self._require_client().eval(
                self._RELEASE_SCRIPT,
                1,
                self._key("claim", key),
                owner,
            )
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis claim release failed") from exc

    async def ticket_put(
        self,
        *,
        key: str,
        payload: str,
        ttl_seconds: int,
    ) -> bool:
        try:
            result = await self._require_client().set(
                self._key("ticket", key),
                payload,
                ex=ttl_seconds,
                nx=True,
            )
            return bool(result)
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis ticket write failed") from exc

    async def ticket_take(self, key: str) -> str | None:
        try:
            value = await self._require_client().eval(
                self._TAKE_SCRIPT,
                1,
                self._key("ticket", key),
            )
            return None if value is None else str(value)
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis ticket consume failed") from exc

    async def publish(self, topic: str, payload: str) -> None:
        try:
            await self._require_client().publish(
                self._key("events", topic),
                payload,
            )
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis publish failed") from exc

    async def subscribe(self, pattern: str, handler: MessageHandler) -> None:
        channel_pattern = self._key("events", pattern)
        try:
            pubsub = await self._open_pubsub(channel_pattern)
        except (RedisError, OSError, TimeoutError) as exc:
            raise CoordinationUnavailableError("Redis subscribe failed") from exc
        self._next_subscription_id += 1
        subscription_id = self._next_subscription_id
        self._subscription_health[subscription_id] = True
        task = asyncio.create_task(
            self._listen(
                subscription_id,
                pubsub,
                channel_pattern,
                handler,
            ),
            name=f"redis-events-{len(self._listener_tasks) + 1}",
        )
        self._listener_tasks.append(task)

    async def _open_pubsub(self, channel_pattern: str) -> Any:
        pubsub = self._require_client().pubsub()
        try:
            await pubsub.psubscribe(channel_pattern)
        except (RedisError, OSError, TimeoutError):
            with suppress(RedisError, OSError, TimeoutError):
                await pubsub.aclose()
            raise
        self._pubsubs.append(pubsub)
        return pubsub

    async def _discard_pubsub(self, pubsub: Any) -> None:
        with suppress(ValueError):
            self._pubsubs.remove(pubsub)
        with suppress(RedisError, OSError, TimeoutError):
            await pubsub.aclose()

    async def _listen(
        self,
        subscription_id: int,
        pubsub: Any,
        channel_pattern: str,
        handler: MessageHandler,
    ) -> None:
        current = pubsub
        backoff = self._RECONNECT_INITIAL_SECONDS
        try:
            while not self._closing:
                try:
                    await self._consume_messages(current, handler)
                except asyncio.CancelledError:
                    raise
                except (RedisError, OSError, TimeoutError):
                    logger.exception("Redis event listener disconnected")
                else:
                    logger.warning("Redis event listener ended; reconnecting")

                self._subscription_health[subscription_id] = False
                await self._discard_pubsub(current)
                if self._closing:
                    return

                while not self._closing:
                    await asyncio.sleep(backoff)
                    try:
                        current = await self._open_pubsub(channel_pattern)
                    except (RedisError, OSError, TimeoutError):
                        logger.exception("Redis event resubscribe failed")
                        backoff = min(backoff * 2, self._RECONNECT_MAX_SECONDS)
                        continue
                    self._subscription_health[subscription_id] = True
                    backoff = self._RECONNECT_INITIAL_SECONDS
                    break
        finally:
            self._subscription_health[subscription_id] = False
            await self._discard_pubsub(current)

    async def _consume_messages(self, pubsub: Any, handler: MessageHandler) -> None:
        while not self._closing:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=self._PUBSUB_POLL_SECONDS,
            )
            if message is None:
                continue
            if message.get("type") not in {"message", "pmessage"}:
                continue
            channel = str(message.get("channel", ""))
            marker = f"{self.prefix}:events:"
            topic = channel.split(marker, 1)[-1]
            try:
                await handler(topic, str(message.get("data", "")))
            except asyncio.CancelledError:
                raise
            except Exception:
                # Consumer validation errors must not terminate Redis listening.
                logger.exception("Redis event consumer rejected a payload")


def coordination_payload(data: dict[str, object]) -> str:
    """Stable compact JSON used by tickets and cross-worker event messages."""

    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)

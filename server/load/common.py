"""Pure helpers shared by the Locust scenario and its unit tests."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

MAX_LOAD_IDENTITIES = 10_000
_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,48}$")


class UserPoolExhausted(RuntimeError):
    """Raised instead of silently sharing state between virtual users."""


class ScenarioDataMissing(RuntimeError):
    """A required seeded catalogue or inventory item was unavailable."""


class RequestEventHook(Protocol):
    def fire(self, **kwargs: object) -> None: ...


@dataclass(frozen=True, slots=True)
class LoadIdentity:
    index: int
    username: str


class UniqueUserAllocator:
    """Allocate each pre-seeded account at most once in a Locust process."""

    def __init__(self, *, prefix: str, count: int, offset: int = 0) -> None:
        if count < 1:
            raise ValueError("load-user count must be positive")
        if offset < 0:
            raise ValueError("load-user offset must not be negative")
        if offset + count > MAX_LOAD_IDENTITIES:
            raise ValueError(f"load-user shard exceeds {MAX_LOAD_IDENTITIES} seeded identities")
        if not _PREFIX_PATTERN.fullmatch(prefix) or len(f"{prefix}{offset + count:05d}") > 64:
            raise ValueError(
                "load-user prefix must produce a valid username of at most 64 characters"
            )
        self.prefix = prefix
        self.count = count
        self.offset = offset
        self._lock = Lock()
        self._claimed = 0

    def claim(self) -> LoadIdentity:
        with self._lock:
            if self._claimed >= self.count:
                raise UserPoolExhausted(
                    f"all {self.count} load identities in this process are already assigned"
                )
            self._claimed += 1
            index = self.offset + self._claimed
        return LoadIdentity(index=index, username=f"{self.prefix}{index:05d}")

    def reset(self) -> None:
        with self._lock:
            self._claimed = 0


def require_scenario_item[ItemT](
    request_event: RequestEventHook,
    items: Sequence[ItemT],
    *,
    scenario: str,
    reason: str,
    predicate: Callable[[ItemT], bool] | None = None,
) -> ItemT:
    """Return required data or emit one Locust failure before raising."""

    selected = next((item for item in items if predicate is None or predicate(item)), None)
    if selected is not None:
        return selected
    error = ScenarioDataMissing(reason)
    request_event.fire(
        request_type="SCENARIO",
        name=scenario,
        response_time=0,
        response_length=0,
        exception=error,
    )
    raise error


def env_int(
    name: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int = 10_000,
) -> int:
    """Read a bounded integer environment setting with an actionable error."""

    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def websocket_url(
    base_url: str,
    path: str,
    query: dict[str, str] | None = None,
) -> str:
    """Convert an HTTP origin and relative API path into a WebSocket URL."""

    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an absolute http:// or https:// URL")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    joined_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    return urlunsplit((scheme, parsed.netloc, joined_path, urlencode(query or {}), ""))

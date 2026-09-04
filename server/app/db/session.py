"""Lazy async SQLAlchemy engine and session lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return
    if url.database == ":memory:" or url.database.startswith("file:"):
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _configure_sqlite_engine(engine: AsyncEngine, database_url: str) -> None:
    """Apply integrity and bounded-concurrency pragmas to every SQLite connection."""

    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    use_wal = bool(
        url.database and url.database != ":memory:" and not url.database.startswith("file:")
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if use_wal:
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


@lru_cache
def get_engine() -> AsyncEngine:
    """Create the process-wide async engine on first database use."""

    settings = get_settings()
    database_url = settings.database_url
    _ensure_sqlite_parent(database_url)
    engine_options: dict[str, object] = {"pool_pre_ping": True}
    if make_url(database_url).drivername.startswith("postgresql"):
        engine_options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
    engine = create_async_engine(database_url, **engine_options)
    _configure_sqlite_engine(engine, database_url)
    return engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create sessions without expiring loaded data after commit."""

    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that owns one transaction-capable async session."""

    async with get_session_factory()() as session:
        yield session


async def dispose_database() -> None:
    """Dispose initialized connections without creating an unused engine."""

    if get_engine.cache_info().currsize:
        engine = get_engine()
        await engine.dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()

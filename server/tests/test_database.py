"""Database safety configuration tests."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.db import session as database
from app.db.session import _configure_sqlite_engine


@pytest.mark.asyncio
async def test_sqlite_connections_enforce_integrity_and_use_wal(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'pragma-test.db'}"
    engine = create_async_engine(database_url)
    _configure_sqlite_engine(engine, database_url)

    async with engine.connect() as connection:
        foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
        busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
        journal_mode = await connection.scalar(text("PRAGMA journal_mode"))

    await engine.dispose()
    assert foreign_keys == 1
    assert busy_timeout == 5000
    assert journal_mode == "wal"


def test_postgres_engine_uses_configured_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()
    settings = Settings(
        database_url="postgresql+asyncpg://tourism:tourism@db/tourism",
        database_pool_size=17,
        database_max_overflow=23,
        database_pool_timeout_seconds=11,
        database_pool_recycle_seconds=900,
    )

    def create_engine(url: str, **options: object) -> object:
        captured["url"] = url
        captured.update(options)
        return sentinel

    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "create_async_engine", create_engine)
    database.get_engine.cache_clear()
    try:
        assert database.get_engine() is sentinel
    finally:
        database.get_engine.cache_clear()

    assert captured == {
        "url": settings.database_url,
        "pool_pre_ping": True,
        "pool_size": 17,
        "max_overflow": 23,
        "pool_timeout": 11.0,
        "pool_recycle": 900,
    }

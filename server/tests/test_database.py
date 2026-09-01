"""Database safety configuration tests."""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

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

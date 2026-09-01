"""Idempotent foundation seed command.

Run after ``alembic upgrade head`` with ``uv run tourism-seed`` or
``uv run python -m app.scripts.seed``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.seed_record import SeedRecord
from app.db.session import dispose_database, get_session_factory

FOUNDATION_SEED_KEY = "foundation-v1"


async def seed_database(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> bool:
    """Apply the foundation seed once; return whether a row was inserted."""

    factory = session_factory or get_session_factory()
    async with factory() as session:
        existing = await session.get(SeedRecord, FOUNDATION_SEED_KEY)
        if existing is not None:
            return False

        session.add(
            SeedRecord(
                key=FOUNDATION_SEED_KEY,
                description="Smart Tourism Service foundation initialized",
            )
        )
        await session.commit()
        return True


async def _main() -> None:
    inserted = await seed_database()
    print("Foundation seed applied." if inserted else "Foundation seed already applied.")
    await dispose_database()


def run() -> None:
    """Synchronous console-script adapter."""

    asyncio.run(_main())


if __name__ == "__main__":
    run()

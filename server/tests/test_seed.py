"""Foundation seed idempotency test."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.seed_record import SeedRecord
from app.scripts.seed import seed_database


async def test_foundation_seed_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    assert await seed_database(session_factory) is True
    assert await seed_database(session_factory) is False

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(SeedRecord))

    assert count == 1
    await engine.dispose()

"""Foundation seed idempotency test."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.role import Role
from app.db.models.seed_record import SeedRecord
from app.db.models.user import User
from app.scripts.seed import DEMO_PASSWORD, seed_database


async def test_foundation_seed_is_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    assert await seed_database(session_factory, include_demo_accounts=True) is True

    async with session_factory() as session:
        first_hash = await session.scalar(
            select(User.password_hash).where(User.username == "admin_demo")
        )

    assert await seed_database(session_factory, include_demo_accounts=True) is False

    async with session_factory() as session:
        seed_count = await session.scalar(select(func.count()).select_from(SeedRecord))
        role_count = await session.scalar(select(func.count()).select_from(Role))
        user_count = await session.scalar(select(func.count()).select_from(User))
        second_hash = await session.scalar(
            select(User.password_hash).where(User.username == "admin_demo")
        )

    assert seed_count == 2
    assert role_count == 4
    assert user_count == 4
    assert first_hash == second_hash
    assert first_hash != DEMO_PASSWORD
    await engine.dispose()

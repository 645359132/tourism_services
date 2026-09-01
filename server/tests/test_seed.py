"""Foundation seed idempotency test."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.guide import (
    Attraction,
    CrowdSnapshot,
    Narration,
    RouteEdge,
    RouteNode,
)
from app.db.models.marketplace import (
    BundleComponent,
    Experience,
    ExperienceSession,
    HospitalityOffer,
    HospitalityVenue,
    InventoryBucket,
    QueueCounter,
    UserScheduleLock,
)
from app.db.models.role import Role
from app.db.models.seed_record import SeedRecord
from app.db.models.ticketing import (
    DynamicPriceRule,
    TicketInventory,
    TicketSlot,
    TicketType,
)
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
        ticket_type_count = await session.scalar(select(func.count()).select_from(TicketType))
        slot_count = await session.scalar(select(func.count()).select_from(TicketSlot))
        inventory_count = await session.scalar(select(func.count()).select_from(TicketInventory))
        price_rule_count = await session.scalar(select(func.count()).select_from(DynamicPriceRule))
        attraction_count = await session.scalar(select(func.count()).select_from(Attraction))
        narration_count = await session.scalar(select(func.count()).select_from(Narration))
        route_node_count = await session.scalar(select(func.count()).select_from(RouteNode))
        route_edge_count = await session.scalar(select(func.count()).select_from(RouteEdge))
        crowd_count = await session.scalar(select(func.count()).select_from(CrowdSnapshot))
        experience_count = await session.scalar(select(func.count()).select_from(Experience))
        experience_session_count = await session.scalar(
            select(func.count()).select_from(ExperienceSession)
        )
        venue_count = await session.scalar(select(func.count()).select_from(HospitalityVenue))
        offer_count = await session.scalar(select(func.count()).select_from(HospitalityOffer))
        bundle_component_count = await session.scalar(
            select(func.count()).select_from(BundleComponent)
        )
        shared_bucket_count = await session.scalar(
            select(func.count()).select_from(InventoryBucket)
        )
        queue_counter_count = await session.scalar(select(func.count()).select_from(QueueCounter))
        schedule_lock_count = await session.scalar(
            select(func.count()).select_from(UserScheduleLock)
        )
        second_hash = await session.scalar(
            select(User.password_hash).where(User.username == "admin_demo")
        )

    assert seed_count == 5
    assert role_count == 4
    assert user_count == 4
    assert ticket_type_count == 4
    assert slot_count == 84
    assert inventory_count == 84
    assert price_rule_count == 2
    assert attraction_count == 8
    assert narration_count == 8
    assert route_node_count == 12
    assert route_edge_count == 15
    assert crowd_count == 8
    assert experience_count == 3
    assert experience_session_count == 63
    assert venue_count == 3
    assert offer_count == 4
    assert bundle_component_count == 2
    assert shared_bucket_count == 121
    assert queue_counter_count == 3
    assert schedule_lock_count == 4
    assert first_hash == second_hash
    assert first_hash != DEMO_PASSWORD
    await engine.dispose()

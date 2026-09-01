"""Idempotent foundation seed command.

Run after ``alembic upgrade head`` with ``uv run tourism-seed`` or
``uv run python -m app.scripts.seed``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.preference import TouristPreference
from app.db.models.role import Role, UserRole
from app.db.models.seed_record import SeedRecord
from app.db.models.ticketing import (
    DynamicPriceRule,
    TicketInventory,
    TicketSlot,
    TicketType,
)
from app.db.models.user import User
from app.db.session import dispose_database, get_session_factory

FOUNDATION_SEED_KEY = "foundation-v1"
AUTH_DEMO_SEED_KEY = "auth-demo-v1"
TICKETING_SEED_KEY = "ticketing-demo-v1"
DEMO_PASSWORD = "Tourism123!"
ROLE_DESCRIPTIONS = {
    "tourist": "Visitor using tourism discovery and personalization features",
    "merchant": "Tourism service merchant operator",
    "support": "Customer support operator",
    "admin": "Platform administrator",
}
DEMO_ACCOUNTS = (
    ("tourist_demo", "游客演示账号", "tourist"),
    ("merchant_demo", "商户演示账号", "merchant"),
    ("support_demo", "客服演示账号", "support"),
    ("admin_demo", "管理员演示账号", "admin"),
)
TICKET_TYPES = (
    ("adult", "成人票", "成人游客", "标准成人景区入园票", 12_000, 1, 100),
    ("child", "儿童票", "符合景区儿童政策的游客", "儿童优惠入园票", 6_000, 1, 60),
    ("student", "学生票", "持有效学生证的游客", "学生优惠入园票", 8_000, 1, 60),
    ("family", "家庭票", "两名成人及两名儿童", "四人家庭组合入园票", 30_000, 4, 20),
)
SLOT_WINDOWS = (
    (time(9, 0), time(12, 0)),
    (time(12, 0), time(15, 0)),
    (time(15, 0), time(18, 0)),
)


async def seed_database(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    include_demo_accounts: bool | None = None,
) -> bool:
    """Apply foundation data and explicitly enabled non-production demos."""

    factory = session_factory or get_session_factory()
    demos_enabled = (
        get_settings().enable_demo_accounts
        if include_demo_accounts is None
        else include_demo_accounts
    )
    async with factory() as session:
        inserted = False
        foundation_seed = await session.get(SeedRecord, FOUNDATION_SEED_KEY)
        if foundation_seed is None:
            session.add(
                SeedRecord(
                    key=FOUNDATION_SEED_KEY,
                    description="Smart Tourism Service foundation initialized",
                )
            )
            inserted = True

        auth_seed = await session.get(SeedRecord, AUTH_DEMO_SEED_KEY)
        if demos_enabled and auth_seed is None:
            roles: dict[str, Role] = {}
            for role_name, description in ROLE_DESCRIPTIONS.items():
                role = await session.scalar(select(Role).where(Role.name == role_name))
                if role is None:
                    role = Role(name=role_name, description=description)
                    session.add(role)
                    await session.flush()
                roles[role_name] = role

            for username, display_name, role_name in DEMO_ACCOUNTS:
                user = await session.scalar(select(User).where(User.username == username))
                if user is None:
                    user = User(
                        username=username,
                        display_name=display_name,
                        password_hash=hash_password(DEMO_PASSWORD),
                        is_active=True,
                    )
                    session.add(user)
                    await session.flush()

                role = roles[role_name]
                assignment = await session.get(
                    UserRole,
                    {"user_id": user.id, "role_id": role.id},
                )
                if assignment is None:
                    session.add(UserRole(user_id=user.id, role_id=role.id))

                if role_name == "tourist":
                    preference = await session.get(TouristPreference, user.id)
                    if preference is None:
                        session.add(
                            TouristPreference(
                                user_id=user.id,
                                preferred_language="zh-CN",
                                interests=[],
                                accessibility_needs=[],
                                notifications_enabled=True,
                            )
                        )

            session.add(
                SeedRecord(
                    key=AUTH_DEMO_SEED_KEY,
                    description="Explicitly enabled local authentication demos initialized",
                )
            )
            inserted = True

        ticketing_seed = await session.get(SeedRecord, TICKETING_SEED_KEY)
        if ticketing_seed is None:
            ticket_types: dict[str, tuple[TicketType, int]] = {}
            for (
                code,
                name,
                audience,
                description,
                base_price_cents,
                admission_count,
                capacity,
            ) in TICKET_TYPES:
                ticket_type = await session.scalar(
                    select(TicketType).where(TicketType.code == code)
                )
                if ticket_type is None:
                    ticket_type = TicketType(
                        code=code,
                        name=name,
                        audience=audience,
                        description=description,
                        base_price_cents=base_price_cents,
                        admission_count=admission_count,
                        is_active=True,
                    )
                    session.add(ticket_type)
                    await session.flush()
                ticket_types[code] = (ticket_type, capacity)

            first_visit_date = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)
            for day_offset in range(7):
                visit_date = first_visit_date + timedelta(days=day_offset)
                for ticket_type, capacity in ticket_types.values():
                    for start_time, end_time in SLOT_WINDOWS:
                        slot = await session.scalar(
                            select(TicketSlot).where(
                                TicketSlot.ticket_type_id == ticket_type.id,
                                TicketSlot.visit_date == visit_date,
                                TicketSlot.start_time == start_time,
                                TicketSlot.end_time == end_time,
                            )
                        )
                        if slot is None:
                            slot = TicketSlot(
                                ticket_type_id=ticket_type.id,
                                visit_date=visit_date,
                                start_time=start_time,
                                end_time=end_time,
                                is_active=True,
                            )
                            slot.inventory = TicketInventory(
                                capacity=capacity,
                                reserved=0,
                                sold=0,
                            )
                            session.add(slot)

            price_rules = (
                DynamicPriceRule(
                    name="Weekend demand adjustment",
                    rule_type="weekend",
                    adjustment_bps=2_000,
                    weekend_only=True,
                    priority=10,
                    is_active=True,
                ),
                DynamicPriceRule(
                    name="High occupancy adjustment",
                    rule_type="occupancy",
                    adjustment_bps=1_500,
                    min_occupancy_bps=7_000,
                    priority=20,
                    is_active=True,
                ),
            )
            for price_rule in price_rules:
                exists = await session.scalar(
                    select(DynamicPriceRule).where(DynamicPriceRule.name == price_rule.name)
                )
                if exists is None:
                    session.add(price_rule)

            session.add(
                SeedRecord(
                    key=TICKETING_SEED_KEY,
                    description="Ticket catalog, seven-day slots, inventory, and demo pricing",
                )
            )
            inserted = True

        await session.commit()
        return inserted


async def _main() -> None:
    inserted = await seed_database()
    print("Application seed applied." if inserted else "Application seed already applied.")
    await dispose_database()


def run() -> None:
    """Synchronous console-script adapter."""

    asyncio.run(_main())


if __name__ == "__main__":
    run()

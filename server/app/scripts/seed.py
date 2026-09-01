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
from app.db.models.guide import (
    Attraction,
    CrowdSnapshot,
    Narration,
    RouteEdge,
    RouteNode,
)
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
GUIDE_SEED_KEY = "guide-demo-v1"
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
ATTRACTIONS = (
    (
        "heritage_gate",
        "古城门",
        "culture",
        "景区历史轴线入口建筑",
        35,
        ["history", "photo"],
        ["wheelchair"],
        10,
        0,
        "MEDIUM",
        4200,
        180,
        8,
    ),
    (
        "museum",
        "文化博物馆",
        "culture",
        "地方历史与非遗专题陈列",
        60,
        ["history", "education", "family"],
        ["wheelchair", "stroller"],
        20,
        0,
        "LOW",
        2600,
        90,
        3,
    ),
    (
        "lake",
        "镜湖",
        "nature",
        "环湖景观与观鸟步道",
        45,
        ["nature", "photo", "restful"],
        ["wheelchair", "stroller"],
        20,
        10,
        "HIGH",
        8200,
        350,
        18,
    ),
    (
        "garden",
        "百草园",
        "nature",
        "本地植物与传统药草园",
        40,
        ["nature", "education", "restful"],
        ["wheelchair", "stroller"],
        10,
        10,
        "MEDIUM",
        5500,
        220,
        9,
    ),
    (
        "tower",
        "观景塔",
        "landmark",
        "俯瞰景区的标志性观景建筑",
        30,
        ["photo", "history"],
        ["wheelchair"],
        30,
        10,
        "HIGH",
        7600,
        120,
        15,
    ),
    (
        "craft",
        "非遗工坊",
        "culture",
        "传统手工艺演示与互动体验",
        50,
        ["culture", "education", "family"],
        ["wheelchair", "stroller"],
        30,
        0,
        "LOW",
        3000,
        100,
        4,
    ),
    (
        "kids",
        "亲子乐园",
        "family",
        "面向亲子游客的自然探索空间",
        55,
        ["family", "animals", "education"],
        ["wheelchair", "stroller"],
        0,
        10,
        "MEDIUM",
        6000,
        240,
        10,
    ),
    (
        "tea",
        "云水茶舍",
        "leisure",
        "传统茶文化与安静休憩空间",
        35,
        ["culture", "restful", "food"],
        ["wheelchair", "stroller"],
        10,
        20,
        "LOW",
        1800,
        60,
        2,
    ),
)


async def _seed_guide_data(session: AsyncSession) -> None:
    attractions: dict[str, Attraction] = {}
    for (
        code,
        name,
        category,
        description,
        visit_minutes,
        tags,
        accessibility,
        x,
        y,
        crowd_level,
        occupancy_bps,
        people_count,
        wait_minutes,
    ) in ATTRACTIONS:
        attraction = await session.scalar(select(Attraction).where(Attraction.code == code))
        if attraction is None:
            attraction = Attraction(
                code=code,
                name=name,
                category=category,
                description=description,
                visit_minutes=visit_minutes,
                tags=tags,
                accessibility=accessibility,
                x=x,
                y=y,
                is_active=True,
            )
            session.add(attraction)
            await session.flush()
        attractions[code] = attraction

        narration = await session.scalar(
            select(Narration).where(
                Narration.attraction_id == attraction.id,
                Narration.language == "zh-CN",
            )
        )
        if narration is None:
            session.add(
                Narration(
                    attraction_id=attraction.id,
                    title=f"{name}文化讲解",
                    language="zh-CN",
                    transcript=f"这是{name}的本地策展文字讲解, 用于展示文化导览流程。",
                    audio_url=None,
                    duration_seconds=max(90, visit_minutes * 4),
                    provider_mode="text_demo",
                )
            )

        snapshot = await session.scalar(
            select(CrowdSnapshot).where(
                CrowdSnapshot.attraction_id == attraction.id,
                CrowdSnapshot.sequence == 1,
            )
        )
        if snapshot is None:
            session.add(
                CrowdSnapshot(
                    attraction_id=attraction.id,
                    crowd_level=crowd_level,
                    occupancy_bps=occupancy_bps,
                    people_count=people_count,
                    wait_minutes=wait_minutes,
                    source="simulated",
                    sequence=1,
                )
            )

    node_specs = [
        ("entrance", "游客中心入口", "ENTRANCE", None, 0, 0, True),
        ("toilet_central", "中心厕所", "TOILET", None, 15, 5, True),
        ("medical", "医务室", "MEDICAL", None, 5, 5, True),
        ("rest_pavilion", "湖畔休息亭", "REST", None, 20, 20, True),
    ]
    node_specs.extend(
        (
            f"node_{code}",
            attraction.name,
            "ATTRACTION",
            attraction,
            attraction.x,
            attraction.y,
            "wheelchair" in attraction.accessibility,
        )
        for code, attraction in attractions.items()
    )
    nodes: dict[str, RouteNode] = {}
    for code, name, kind, attraction, x, y, accessible in node_specs:
        node = await session.scalar(select(RouteNode).where(RouteNode.code == code))
        if node is None:
            node = RouteNode(
                code=code,
                name=name,
                kind=kind,
                attraction_id=attraction.id if attraction is not None else None,
                x=x,
                y=y,
                accessible=accessible,
            )
            session.add(node)
            await session.flush()
        nodes[code] = node

    edge_specs = (
        ("entrance", "node_heritage_gate", 3, 180, True, True),
        ("entrance", "node_kids", 5, 300, True, True),
        ("entrance", "medical", 2, 100, True, True),
        ("node_heritage_gate", "node_museum", 4, 240, True, True),
        ("node_heritage_gate", "node_garden", 6, 360, True, True),
        ("node_museum", "node_craft", 4, 240, True, True),
        ("node_museum", "node_lake", 5, 300, True, True),
        ("node_museum", "toilet_central", 2, 100, True, True),
        ("node_craft", "node_tower", 3, 150, False, False),
        ("node_lake", "node_garden", 4, 240, True, True),
        ("node_lake", "rest_pavilion", 4, 220, True, True),
        ("node_garden", "node_kids", 5, 280, True, True),
        ("node_garden", "node_tea", 5, 260, True, True),
        ("node_tea", "rest_pavilion", 4, 220, True, True),
        ("node_tower", "rest_pavilion", 5, 280, True, True),
    )
    for from_code, to_code, walk, distance, wheelchair_ok, stroller_ok in edge_specs:
        from_node = nodes[from_code]
        to_node = nodes[to_code]
        edge = await session.scalar(
            select(RouteEdge).where(
                RouteEdge.from_node_id == from_node.id,
                RouteEdge.to_node_id == to_node.id,
            )
        )
        if edge is None:
            session.add(
                RouteEdge(
                    from_node_id=from_node.id,
                    to_node_id=to_node.id,
                    walk_minutes=walk,
                    distance_meters=distance,
                    accessible=wheelchair_ok and stroller_ok,
                    wheelchair_ok=wheelchair_ok,
                    stroller_ok=stroller_ok,
                    bidirectional=True,
                )
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

        guide_seed = await session.get(SeedRecord, GUIDE_SEED_KEY)
        if guide_seed is None:
            await _seed_guide_data(session)
            session.add(
                SeedRecord(
                    key=GUIDE_SEED_KEY,
                    description=("Schematic guide graph, curated text demos, and simulated crowds"),
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

"""Idempotent foundation seed command.

Run after ``alembic upgrade head`` with ``uv run tourism-seed`` or
``uv run python -m app.scripts.seed``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models.commerce import (
    Campaign,
    PointAccount,
    PointLedgerEntry,
    Product,
    ProductInventory,
    Reward,
    ShopCategory,
)
from app.db.models.engagement import FAQ, FacilityPOI
from app.db.models.guide import (
    Attraction,
    CrowdSnapshot,
    Narration,
    RouteEdge,
    RouteNode,
)
from app.db.models.journey import (
    EmergencyBulletin,
    EmergencyResource,
    GreenTask,
    OfflineAsset,
    OfflinePack,
    PassportStampDefinition,
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
MARKETPLACE_SEED_KEY = "marketplace-demo-v1"
CHECKPOINT7_SEED_KEY = "checkpoint7-demo-v1"
CHECKPOINT8_SEED_KEY = "checkpoint8-demo-v1"
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


def _scenic_utc(day, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)


async def _seed_marketplace_data(session: AsyncSession) -> None:
    nodes = {
        node.code: node
        for node in await session.scalars(
            select(RouteNode).where(
                RouteNode.code.in_(
                    (
                        "node_tower",
                        "node_craft",
                        "node_lake",
                        "node_tea",
                        "node_garden",
                    )
                )
            )
        )
    }
    experience_specs = (
        (
            "sky_coaster",
            "RIDE",
            "凌云飞车",
            "山地观景轨道体验; 排队与 FastPass 均为本地演示",
            "node_tower",
            12,
            120,
            True,
            3_800,
            ["wheelchair-transfer"],
            35,
            16,
        ),
        (
            "heritage_show",
            "SHOW",
            "非遗光影秀",
            "定时文化演出, 使用真实服务端场次库存",
            "node_craft",
            45,
            0,
            False,
            0,
            ["wheelchair", "stroller"],
            20,
            60,
        ),
        (
            "lake_boat",
            "RIDE",
            "镜湖游船",
            "亲子游船体验; 实时队列由模拟发布器驱动",
            "node_lake",
            25,
            0,
            True,
            2_600,
            ["wheelchair", "stroller"],
            25,
            24,
        ),
    )
    experiences: dict[str, Experience] = {}
    experience_capacity: dict[str, int] = {}
    for (
        code,
        kind,
        name,
        description,
        node_code,
        duration_minutes,
        min_height_cm,
        fastpass_allowed,
        fastpass_price_cents,
        accessibility,
        wait_minutes,
        capacity,
    ) in experience_specs:
        experience = await session.scalar(select(Experience).where(Experience.code == code))
        if experience is None:
            experience = Experience(
                code=code,
                kind=kind,
                name=name,
                description=description,
                node_id=nodes[node_code].id,
                duration_minutes=duration_minutes,
                min_height_cm=min_height_cm,
                fastpass_allowed=fastpass_allowed,
                fastpass_price_cents=fastpass_price_cents,
                accessibility=accessibility,
                wait_minutes=wait_minutes,
                is_active=True,
            )
            session.add(experience)
            await session.flush()
        experiences[code] = experience
        experience_capacity[code] = capacity
        if await session.get(QueueCounter, experience.id) is None:
            session.add(QueueCounter(experience_id=experience.id, next_sequence=1))

    scenic_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    first_visit_date = scenic_today + timedelta(days=1)
    session_windows = (time(10, 0), time(14, 0), time(17, 0))
    for day_offset in range(7):
        business_date = first_visit_date + timedelta(days=day_offset)
        for code, experience in experiences.items():
            capacity = experience_capacity[code]
            for start_clock in session_windows:
                starts_at = _scenic_utc(business_date, start_clock)
                ends_at = starts_at + timedelta(minutes=experience.duration_minutes)
                experience_session = await session.scalar(
                    select(ExperienceSession).where(
                        ExperienceSession.experience_id == experience.id,
                        ExperienceSession.starts_at == starts_at,
                    )
                )
                if experience_session is None:
                    experience_session = ExperienceSession(
                        experience_id=experience.id,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        capacity=capacity,
                        status="OPEN",
                    )
                    session.add(experience_session)
                    await session.flush()
                bucket = await session.scalar(
                    select(InventoryBucket).where(
                        InventoryBucket.resource_type == "EXPERIENCE_SESSION",
                        InventoryBucket.resource_id == experience_session.id,
                        InventoryBucket.starts_at == starts_at,
                    )
                )
                if bucket is None:
                    session.add(
                        InventoryBucket(
                            resource_type="EXPERIENCE_SESSION",
                            resource_id=experience_session.id,
                            business_date=business_date,
                            starts_at=starts_at,
                            ends_at=ends_at,
                            capacity=capacity,
                            held=0,
                            confirmed=0,
                        )
                    )

    for day_offset in range(8):
        business_date = scenic_today + timedelta(days=day_offset)
        starts_at = _scenic_utc(business_date, time(0, 0))
        ends_at = starts_at + timedelta(days=1)
        for experience in experiences.values():
            if not experience.fastpass_allowed:
                continue
            bucket = await session.scalar(
                select(InventoryBucket).where(
                    InventoryBucket.resource_type == "FAST_PASS",
                    InventoryBucket.resource_id == experience.id,
                    InventoryBucket.starts_at == starts_at,
                )
            )
            if bucket is None:
                session.add(
                    InventoryBucket(
                        resource_type="FAST_PASS",
                        resource_id=experience.id,
                        business_date=business_date,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        capacity=8,
                        held=0,
                        confirmed=0,
                    )
                )

    venue_specs = (
        (
            "cloud_hotel",
            "HOTEL",
            "云栖景区酒店",
            "景区内演示酒店; 未连接真实 PMS",
            "游客中心东侧 200 米",
            "node_tea",
            ["wheelchair", "stroller"],
            ["早餐", "行李寄存", "无障碍客房"],
            47,
        ),
        (
            "garden_homestay",
            "HOMESTAY",
            "百草园民宿",
            "本地演示民宿; 房态来自共享库存桶",
            "百草园南门",
            "node_garden",
            ["stroller"],
            ["庭院", "亲子用品"],
            45,
        ),
        (
            "tea_restaurant",
            "RESTAURANT",
            "云水餐厅",
            "景区套餐时段演示; 未连接真实商家系统",
            "云水茶舍旁",
            "node_tea",
            ["wheelchair", "stroller"],
            ["儿童椅", "素食选项"],
            46,
        ),
    )
    venues: dict[str, HospitalityVenue] = {}
    for (
        code,
        kind,
        name,
        description,
        address,
        node_code,
        accessibility,
        amenities,
        rating_tenths,
    ) in venue_specs:
        venue = await session.scalar(select(HospitalityVenue).where(HospitalityVenue.code == code))
        if venue is None:
            venue = HospitalityVenue(
                code=code,
                kind=kind,
                name=name,
                description=description,
                address=address,
                node_id=nodes[node_code].id,
                accessibility=accessibility,
                amenities=amenities,
                rating_tenths=rating_tenths,
                is_demo=True,
            )
            session.add(venue)
            await session.flush()
        venues[code] = venue

    offer_specs = (
        (
            "lake_room",
            "cloud_hotel",
            "ROOM",
            "湖景家庭房",
            "一张大床与亲子沙发床",
            68_000,
            8,
            4,
        ),
        (
            "garden_room",
            "garden_homestay",
            "ROOM",
            "庭院双人房",
            "安静庭院房型",
            42_000,
            6,
            3,
        ),
        (
            "heritage_meal",
            "tea_restaurant",
            "MEAL",
            "非遗风味套餐",
            "含素食替换选项的时段套餐",
            8_800,
            24,
            10,
        ),
        (
            "stay_play_bundle",
            "cloud_hotel",
            "BUNDLE",
            "住玩组合",
            "一晚湖景房与凌云飞车场次组合",
            29_800,
            8,
            4,
        ),
    )
    offers: dict[str, HospitalityOffer] = {}
    for (
        code,
        venue_code,
        kind,
        name,
        description,
        price,
        capacity,
        max_party_size,
    ) in offer_specs:
        offer = await session.scalar(select(HospitalityOffer).where(HospitalityOffer.code == code))
        if offer is None:
            offer = HospitalityOffer(
                venue_id=venues[venue_code].id,
                code=code,
                kind=kind,
                name=name,
                description=description,
                unit_price_cents=price,
                capacity_per_bucket=capacity,
                max_party_size=max_party_size,
                is_active=True,
            )
            session.add(offer)
            await session.flush()
        offers[code] = offer

    bundle = offers["stay_play_bundle"]
    component_specs = (
        ("ROOM", offers["lake_room"].id, offers["lake_room"].name, 1, 0),
        ("EXPERIENCE", experiences["sky_coaster"].id, experiences["sky_coaster"].name, 1, 0),
    )
    for component_type, resource_id, name, quantity, offset_minutes in component_specs:
        component = await session.scalar(
            select(BundleComponent).where(
                BundleComponent.bundle_offer_id == bundle.id,
                BundleComponent.component_type == component_type,
                BundleComponent.component_resource_id == resource_id,
            )
        )
        if component is None:
            session.add(
                BundleComponent(
                    bundle_offer_id=bundle.id,
                    component_type=component_type,
                    component_resource_id=resource_id,
                    component_name=name,
                    quantity=quantity,
                    offset_minutes=offset_minutes,
                )
            )

    for day_offset in range(14):
        business_date = first_visit_date + timedelta(days=day_offset)
        room_start = _scenic_utc(business_date, time(15, 0))
        room_end = _scenic_utc(business_date + timedelta(days=1), time(11, 0))
        for code in ("lake_room", "garden_room"):
            offer = offers[code]
            bucket = await session.scalar(
                select(InventoryBucket).where(
                    InventoryBucket.resource_type == "ROOM",
                    InventoryBucket.resource_id == offer.id,
                    InventoryBucket.starts_at == room_start,
                )
            )
            if bucket is None:
                session.add(
                    InventoryBucket(
                        resource_type="ROOM",
                        resource_id=offer.id,
                        business_date=business_date,
                        starts_at=room_start,
                        ends_at=room_end,
                        capacity=offer.capacity_per_bucket,
                        held=0,
                        confirmed=0,
                    )
                )
        if day_offset < 7:
            meal_offer = offers["heritage_meal"]
            for start_clock, end_clock in (
                (time(12, 0), time(14, 0)),
                (time(18, 0), time(20, 0)),
            ):
                meal_start = _scenic_utc(business_date, start_clock)
                meal_end = _scenic_utc(business_date, end_clock)
                bucket = await session.scalar(
                    select(InventoryBucket).where(
                        InventoryBucket.resource_type == "MEAL",
                        InventoryBucket.resource_id == meal_offer.id,
                        InventoryBucket.starts_at == meal_start,
                    )
                )
                if bucket is None:
                    session.add(
                        InventoryBucket(
                            resource_type="MEAL",
                            resource_id=meal_offer.id,
                            business_date=business_date,
                            starts_at=meal_start,
                            ends_at=meal_end,
                            capacity=meal_offer.capacity_per_bucket,
                            held=0,
                            confirmed=0,
                        )
                    )

    for user_id in await session.scalars(select(User.id)):
        if await session.get(UserScheduleLock, user_id) is None:
            session.add(UserScheduleLock(user_id=user_id, version=1))


async def _seed_checkpoint7_data(session: AsyncSession) -> None:
    category_specs = (
        ("culture", "文化文创", "景区文化主题纪念品", 10),
        ("green", "绿色出行", "可重复使用与低碳旅行用品", 20),
        ("food", "地方风味", "本地演示食品与茶礼", 30),
    )
    categories: dict[str, ShopCategory] = {}
    for code, name, description, sort_order in category_specs:
        category = await session.scalar(select(ShopCategory).where(ShopCategory.code == code))
        if category is None:
            category = ShopCategory(
                code=code,
                name=name,
                description=description,
                sort_order=sort_order,
                is_active=True,
            )
            session.add(category)
            await session.flush()
        categories[code] = category

    product_specs = (
        (
            "CULTURE-PASSPORT",
            "culture",
            "文化数字护照册",
            "用于记录景区文化印章的实体纪念册",
            3_900,
            300,
            ["文化", "护照", "纪念"],
            60,
        ),
        (
            "CRAFT-KIT",
            "culture",
            "非遗手作体验包",
            "含本地演示材料的亲子手作包",
            6_800,
            None,
            ["亲子", "非遗"],
            30,
        ),
        (
            "GREEN-BOTTLE",
            "green",
            "景区环保水杯",
            "可重复使用的轻量随行杯",
            5_000,
            400,
            ["绿色", "低碳"],
            50,
        ),
        (
            "TEA-GIFT",
            "food",
            "云水茶礼",
            "本地茶文化演示礼盒",
            8_800,
            None,
            ["茶文化", "伴手礼"],
            25,
        ),
    )
    products: dict[str, Product] = {}
    for (
        sku,
        category_code,
        name,
        description,
        price,
        points_price,
        tags,
        stock,
    ) in product_specs:
        product = await session.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            product = Product(
                category_id=categories[category_code].id,
                sku=sku,
                name=name,
                description=description,
                price_cents=price,
                points_price=points_price,
                tags=tags,
                image_url=None,
                is_active=True,
                is_demo=True,
            )
            product.inventory = ProductInventory(stock=stock, version=1)
            session.add(product)
            await session.flush()
        products[sku] = product

    campaign = await session.scalar(select(Campaign).where(Campaign.code == "green-month"))
    now = datetime.now(UTC)
    if campaign is None:
        campaign = Campaign(
            code="green-month",
            name="绿色出行月",
            description="环保用品本地演示限时折扣",
            product_id=products["GREEN-BOTTLE"].id,
            category_id=None,
            discount_bps=2_000,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=30),
            is_active=True,
        )
        session.add(campaign)
    elif (
        campaign.ends_at
        if campaign.ends_at.tzinfo is not None
        else campaign.ends_at.replace(tzinfo=UTC)
    ) <= now + timedelta(days=7):
        campaign.starts_at = now - timedelta(days=1)
        campaign.ends_at = now + timedelta(days=30)

    reward_specs = (
        ("passport_stamp", "文化探索纪念章", "演示文化任务纪念章", 150, 30),
        ("green_coupon", "绿色餐饮优惠券", "演示积分兑换优惠券", 200, 20),
        ("rest_pass", "休息区饮品券", "演示休息点饮品兑换", 100, 40),
    )
    for code, name, description, points_cost, stock in reward_specs:
        reward = await session.scalar(select(Reward).where(Reward.code == code))
        if reward is None:
            session.add(
                Reward(
                    code=code,
                    name=name,
                    description=description,
                    points_cost=points_cost,
                    stock=stock,
                    is_active=True,
                    is_demo=True,
                )
            )

    faq_specs = (
        ("ticket_refund", "票务", "如何申请退票?", "在订单详情按退改规则提交申请.", 10),
        ("queue_fastpass", "项目", "快速通行券是否真实扣款?", "当前为明确标注的本地演示支付.", 20),
        (
            "offline_pack",
            "离线",
            "弱网时还能查看电子票吗?",
            "同步过的离线旅行包可查看核心票据与行程.",
            30,
        ),
        ("support_sos", "应急", "紧急情况如何求助?", "优先联系现场人员并使用 SOS 入口.", 40),
    )
    for code, category, question, answer, sort_order in faq_specs:
        faq = await session.scalar(select(FAQ).where(FAQ.code == code))
        if faq is None:
            session.add(
                FAQ(
                    code=code,
                    category=category,
                    question=question,
                    answer=answer,
                    sort_order=sort_order,
                    is_active=True,
                )
            )

    nodes = {
        node.code: node
        for node in await session.scalars(
            select(RouteNode).where(
                RouteNode.code.in_(("entrance", "toilet_central", "medical", "rest_pavilion"))
            )
        )
    }
    facility_specs = (
        (
            "visitor_center",
            "SERVICE",
            "游客服务中心",
            "咨询, 失物招领与无障碍协助",
            "entrance",
            True,
            True,
            True,
            False,
        ),
        (
            "toilet_central",
            "TOILET",
            "中心无障碍厕所",
            "含无障碍厕位与母婴设施",
            "toilet_central",
            True,
            True,
            True,
            True,
        ),
        (
            "medical_station",
            "MEDICAL",
            "景区医务室",
            "提供基础急救与现场转介",
            "medical",
            True,
            True,
            True,
            False,
        ),
        (
            "lake_rest",
            "REST",
            "湖畔休息亭",
            "适老座椅与亲子休息点",
            "rest_pavilion",
            True,
            True,
            True,
            False,
        ),
    )
    for (
        code,
        kind,
        name,
        description,
        node_code,
        accessible,
        wheelchair_ok,
        stroller_ok,
        baby_care,
    ) in facility_specs:
        facility = await session.scalar(select(FacilityPOI).where(FacilityPOI.code == code))
        if facility is None:
            session.add(
                FacilityPOI(
                    code=code,
                    name=name,
                    category=kind,
                    description=description,
                    node_id=nodes[node_code].id,
                    accessible=accessible,
                    wheelchair_ok=wheelchair_ok,
                    stroller_accessible=stroller_ok,
                    baby_care=baby_care,
                    open_status="OPEN",
                    source="curated_demo",
                    is_demo=True,
                )
            )

    for user_id in await session.scalars(select(User.id)):
        source_id = uuid5(NAMESPACE_URL, f"smart-tourism-welcome:{user_id}")
        existing_ledger = await session.scalar(
            select(PointLedgerEntry).where(
                PointLedgerEntry.user_id == user_id,
                PointLedgerEntry.source_type == "WELCOME",
                PointLedgerEntry.source_id == source_id,
                PointLedgerEntry.entry_type == "EARN",
            )
        )
        if existing_ledger is not None:
            continue
        account = await session.get(PointAccount, user_id)
        if account is None:
            account = PointAccount(user_id=user_id, balance=0, version=1)
            session.add(account)
            await session.flush()
        account.balance += 500
        account.version += 1
        session.add(
            PointLedgerEntry(
                user_id=user_id,
                entry_type="EARN",
                delta=500,
                balance_after=account.balance,
                source_type="WELCOME",
                source_id=source_id,
                description="本地演示欢迎积分",
            )
        )


async def _seed_checkpoint8_data(session: AsyncSession) -> None:
    asset_specs = (
        (
            "core-map",
            "MAP",
            "景区核心离线地图",
            {
                "version": 1,
                "nodes": [
                    {"code": "entrance", "name": "游客中心入口"},
                    {"code": "medical", "name": "医务室"},
                    {"code": "toilet_central", "name": "中心厕所"},
                    {"code": "rest_pavilion", "name": "湖畔休息亭"},
                ],
            },
            True,
        ),
        (
            "travel-guide",
            "GUIDE",
            "离线旅行核心说明",
            {
                "sections": [
                    "电子票和行程需在联网时完成同步",
                    "离线包不替代现场安全指引",
                    "恢复联网后使用游标同步变更",
                ]
            },
            True,
        ),
        (
            "emergency-guide",
            "EMERGENCY",
            "离线应急指引",
            {
                "steps": [
                    "保持冷静并观察现场疏散标识",
                    "优先联系现场工作人员",
                    "演示 SOS 不会联系真实急救机构",
                ]
            },
            True,
        ),
        (
            "culture-intro",
            "CULTURE",
            "文化护照离线简介",
            {"stamps": ["古城门", "文化博物馆", "非遗工坊"]},
            False,
        ),
        (
            "narration-core",
            "NARRATION",
            "核心文化离线讲解",
            {
                "language": "zh-CN",
                "provider_mode": "text_demo",
                "chapters": [
                    {
                        "code": "heritage_gate_intro",
                        "title": "古城门文化导览",
                        "duration_seconds": 45,
                        "transcript": (
                            "古城门位于景区历史轴线入口, 建筑形制展示了本地传统营造与城镇记忆."
                        ),
                    },
                    {
                        "code": "museum_intro",
                        "title": "文化博物馆导览",
                        "duration_seconds": 55,
                        "transcript": (
                            "文化博物馆通过地方史与非遗陈列, 串联景区的自然环境和社区生活."
                        ),
                    },
                ],
            },
            True,
        ),
    )
    manifest_items: list[dict[str, object]] = []
    prepared_assets: list[tuple[str, str, str, dict[str, object], bool, str, int]] = []
    for asset_key, kind, title, payload, required in asset_specs:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        content_hash = sha256(encoded).hexdigest()
        size_bytes = len(encoded)
        prepared_assets.append(
            (
                asset_key,
                kind,
                title,
                payload,
                required,
                content_hash,
                size_bytes,
            )
        )
        manifest_items.append(
            {
                "asset_key": asset_key,
                "content_hash": content_hash,
                "kind": kind,
                "required": required,
                "size_bytes": size_bytes,
                "title": title,
            }
        )
    manifest_items.sort(key=lambda item: str(item["asset_key"]))
    manifest_encoded = json.dumps(
        manifest_items,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    manifest_hash = sha256(manifest_encoded).hexdigest()
    pack_etag = sha256(f"offline-pack-v1:{manifest_hash}".encode()).hexdigest()
    pack_id = uuid5(NAMESPACE_URL, "smart-tourism-offline-pack-v1")
    pack = await session.get(OfflinePack, pack_id)
    if pack is None:
        pack = OfflinePack(
            id=pack_id,
            version=1,
            name="智慧景区离线旅行包",
            description="核心地图, 应急说明, 同步规则与文化简介",
            etag=pack_etag,
            manifest_hash=manifest_hash,
            published_at=datetime.now(UTC),
            expires_at=None,
            is_active=True,
            is_demo=True,
        )
        session.add(pack)
        await session.flush()
    for (
        asset_key,
        kind,
        title,
        payload,
        required,
        content_hash,
        size_bytes,
    ) in prepared_assets:
        asset = await session.scalar(
            select(OfflineAsset).where(
                OfflineAsset.pack_id == pack.id,
                OfflineAsset.asset_key == asset_key,
            )
        )
        if asset is None:
            session.add(
                OfflineAsset(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"smart-tourism-offline-pack-v1:{asset_key}",
                    ),
                    pack_id=pack.id,
                    asset_key=asset_key,
                    kind=kind,
                    title=title,
                    content_hash=content_hash,
                    size_bytes=size_bytes,
                    required=required,
                    payload=payload,
                )
            )
        else:
            asset.kind = kind
            asset.title = title
            asset.payload = payload
            asset.required = required
            asset.content_hash = content_hash
            asset.size_bytes = size_bytes
    await session.flush()
    canonical_asset_keys = {item[0] for item in prepared_assets}
    persisted_assets = list(
        await session.scalars(select(OfflineAsset).where(OfflineAsset.pack_id == pack.id))
    )
    for persisted_asset in persisted_assets:
        if persisted_asset.asset_key not in canonical_asset_keys:
            await session.delete(persisted_asset)
    pack.name = "智慧景区离线旅行包"
    pack.description = "核心地图, 应急说明, 同步规则与文化简介"
    pack.etag = pack_etag
    pack.manifest_hash = manifest_hash
    pack.is_active = True
    pack.is_demo = True

    nodes = {
        node.code: node
        for node in await session.scalars(
            select(RouteNode).where(
                RouteNode.code.in_(
                    (
                        "entrance",
                        "medical",
                        "toilet_central",
                        "rest_pavilion",
                        "node_heritage_gate",
                        "node_museum",
                        "node_craft",
                    )
                )
            )
        )
    }
    resource_specs = (
        (
            "medical",
            "MEDICAL",
            "景区医务室",
            "基础急救与现场转介",
            "120",
            "medical",
            ["优先联系现场工作人员", "危急情况拨打当地急救电话"],
            10,
        ),
        (
            "evacuation",
            "EVACUATION",
            "游客中心疏散集合点",
            "按现场广播和标识前往集合",
            None,
            "entrance",
            ["不要逆行", "照顾儿童和行动不便游客"],
            20,
        ),
        (
            "lost_help",
            "LOST_HELP",
            "走散协助点",
            "在游客中心登记并等待工作人员协助",
            None,
            "entrance",
            ["不要独自进入封闭区域", "保持通讯设备可用"],
            30,
        ),
    )
    for (
        code,
        kind,
        title,
        description,
        phone,
        node_code,
        instructions,
        priority,
    ) in resource_specs:
        resource = await session.scalar(
            select(EmergencyResource).where(EmergencyResource.code == code)
        )
        if resource is None:
            session.add(
                EmergencyResource(
                    code=code,
                    kind=kind,
                    title=title,
                    description=description,
                    phone=phone,
                    node_id=nodes[node_code].id,
                    instructions=instructions,
                    priority=priority,
                    is_active=True,
                    is_demo=True,
                )
            )

    now = datetime.now(UTC)
    bulletin = await session.scalar(
        select(EmergencyBulletin).where(EmergencyBulletin.code == "demo-safety")
    )
    if bulletin is None:
        session.add(
            EmergencyBulletin(
                code="demo-safety",
                title="演示安全提示",
                content="请遵循现场标识. 本提示为本地种子数据.",
                severity="INFO",
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=30),
                is_active=True,
                is_demo=True,
            )
        )
    elif (
        bulletin.ends_at
        if bulletin.ends_at.tzinfo is not None
        else bulletin.ends_at.replace(tzinfo=UTC)
    ) <= now + timedelta(days=7):
        bulletin.starts_at = now - timedelta(days=1)
        bulletin.ends_at = now + timedelta(days=30)

    stamp_specs = (
        (
            "heritage_gate",
            "古城门印章",
            "探索景区历史轴线入口",
            "node_heritage_gate",
            30,
        ),
        (
            "museum",
            "文化博物馆印章",
            "完成地方文化主题探索",
            "node_museum",
            40,
        ),
        (
            "craft",
            "非遗工坊印章",
            "体验传统手工艺文化",
            "node_craft",
            35,
        ),
    )
    for code, title, description, node_code, points in stamp_specs:
        definition = await session.scalar(
            select(PassportStampDefinition).where(PassportStampDefinition.code == code)
        )
        if definition is None:
            session.add(
                PassportStampDefinition(
                    code=code,
                    title=title,
                    description=description,
                    node_id=nodes[node_code].id,
                    points_award=points,
                    is_active=True,
                    is_demo=True,
                )
            )

    task_specs = (
        (
            "public_transport",
            "TRANSPORT",
            "绿色到达",
            "使用公共交通或景区接驳到达",
            25,
            "填写演示出行方式",
        ),
        (
            "water_refill",
            "REFILL",
            "环保补水",
            "使用可重复水杯完成补水",
            20,
            "填写演示补水点",
        ),
        (
            "culture_walk",
            "CULTURE",
            "文化步行探索",
            "步行完成一段文化路线",
            30,
            "填写演示路线名称",
        ),
        (
            "recycle",
            "RECYCLE",
            "垃圾分类",
            "在景区分类投放点完成分类",
            15,
            "填写演示投放点",
        ),
    )
    for code, kind, title, description, points, evidence_hint in task_specs:
        task = await session.scalar(select(GreenTask).where(GreenTask.code == code))
        if task is None:
            session.add(
                GreenTask(
                    code=code,
                    kind=kind,
                    title=title,
                    description=description,
                    points_award=points,
                    evidence_hint=evidence_hint,
                    is_active=True,
                    is_demo=True,
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

        marketplace_seed = await session.get(SeedRecord, MARKETPLACE_SEED_KEY)
        if marketplace_seed is None:
            session.add(
                SeedRecord(
                    key=MARKETPLACE_SEED_KEY,
                    description=(
                        "Experience sessions, shared reservation inventory, queues, "
                        "FastPass quotas, hospitality, bundles, and reviews"
                    ),
                )
            )
            inserted = True
        await _seed_marketplace_data(session)

        checkpoint7_seed = await session.get(SeedRecord, CHECKPOINT7_SEED_KEY)
        if checkpoint7_seed is None:
            session.add(
                SeedRecord(
                    key=CHECKPOINT7_SEED_KEY,
                    description=(
                        "Shop, campaigns, points, rewards, FAQs, facilities, "
                        "support, and collaboration demos"
                    ),
                )
            )
            inserted = True
        await _seed_checkpoint7_data(session)

        checkpoint8_seed = await session.get(SeedRecord, CHECKPOINT8_SEED_KEY)
        if checkpoint8_seed is None:
            session.add(
                SeedRecord(
                    key=CHECKPOINT8_SEED_KEY,
                    description=(
                        "Offline pack, sync, emergency, SOS, passport, and green task demos"
                    ),
                )
            )
            inserted = True
        await _seed_checkpoint8_data(session)

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

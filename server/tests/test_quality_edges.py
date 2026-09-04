"""Focused edge coverage for stable schemas, providers, auth, and errors."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import auth as auth_dependencies
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    create_ticket_qr,
    password_needs_rehash,
    verify_password,
)
from app.db.models.commerce import Campaign, Redemption, Reward
from app.db.models.guide import Attraction, CrowdSnapshot, RouteEdge, RouteNode
from app.db.models.marketplace import (
    RESERVATION_EXPIRED,
    RESERVATION_HELD,
    HospitalityOffer,
)
from app.db.models.ticketing import (
    ORDER_PAID,
    DynamicPriceRule,
    ElectronicTicket,
    TicketInventory,
    TicketOrder,
    TicketSlot,
    TicketType,
)
from app.db.models.user import User
from app.providers.journey import (
    DemoCheckInVerifier,
    DemoEmergencyProvider,
    DemoGreenTaskVerifier,
)
from app.providers.map import NoSchematicRouteError, SchematicMapProvider
from app.providers.payment import DemoPaymentProvider
from app.providers.planner import PlanningPreferences, RulesPlanner
from app.providers.share import DemoShareVerifier
from app.providers.support import DemoSupportBot
from app.services import commerce, groups, hospitality, itinerary, points, reservations, ticketing


@pytest.mark.asyncio
async def test_demo_provider_boundaries_are_deterministic_and_explicit() -> None:
    payment = DemoPaymentProvider()
    first = await payment.authorize(
        order_no="ORDER-1",
        amount_cents=12_500,
        idempotency_key="payment-key-0001",
    )
    replay = await payment.authorize(
        order_no="ORDER-1",
        amount_cents=12_500,
        idempotency_key="payment-key-0001",
    )
    assert first == replay
    assert first.reference.startswith("demo_pay_")
    assert first.is_demo is True
    with pytest.raises(ValueError, match="positive"):
        await payment.authorize(
            order_no="ORDER-1",
            amount_cents=0,
            idempotency_key="payment-key-0002",
        )

    bot = DemoSupportBot()
    priority = await bot.reply(message="游客受伤,需要紧急帮助")
    policy = await bot.reply(message="如何申请退款或改签")
    ordinary = await bot.reply(message="集合地点在哪里")
    assert "优先事项" in priority.content
    assert "退改申请" in policy.content
    assert "演示客服" in ordinary.content
    assert all(reply.is_demo for reply in (priority, policy, ordinary))

    shares = DemoShareVerifier()
    assert (
        await shares.verify(
            content_type="PRODUCT",
            ref_id="product-1",
            platform="demo",
            caption="景区好物",
        )
    ).points_awarded == 25
    assert (
        await shares.verify(
            content_type="PRODUCT",
            ref_id="product-1",
            platform=" ",
            caption="景区好物",
        )
    ).verified is False

    emergency = DemoEmergencyProvider()
    dispatch = await emergency.submit(
        user_id="tourist-1",
        kind="LOST",
        message="与同行成员走散",
        idempotency_key="sos-key-0001",
    )
    replayed_dispatch = await emergency.submit(
        user_id="tourist-1",
        kind="LOST",
        message="与同行成员走散",
        idempotency_key="sos-key-0001",
    )
    assert dispatch == replayed_dispatch
    assert dispatch.dispatched_real_services is False

    check_in = DemoCheckInVerifier()
    green = DemoGreenTaskVerifier()
    assert (await check_in.verify(stamp_code=" ")).verified is False
    assert (await check_in.verify(stamp_code="STAMP-1")).verified is True
    assert (await green.verify(evidence="步")).verified is False
    assert (await green.verify(evidence="步行")).verified is True


def _attraction(
    *,
    tags: list[str],
    accessibility: list[str] | None = None,
    visit_minutes: int = 75,
) -> Attraction:
    return Attraction(
        id=uuid4(),
        code=f"attraction-{uuid4().hex[:8]}",
        name="测试景点",
        category="museum",
        description="规则规划测试",
        visit_minutes=visit_minutes,
        tags=tags,
        accessibility=accessibility or [],
        x=0,
        y=0,
        is_active=True,
    )


def _crowd(level: str) -> CrowdSnapshot:
    return CrowdSnapshot(
        id=uuid4(),
        attraction_id=uuid4(),
        crowd_level=level,
        occupancy_bps=5000,
        wait_minutes=10,
        people_count=100,
        source="simulated",
        sequence=1,
    )


def test_rules_planner_applies_accessibility_and_low_fitness_penalties() -> None:
    scored = RulesPlanner().score_candidate(
        attraction=_attraction(
            tags=["Education", "family"],
            accessibility=["wheelchair"],
        ),
        crowd=_crowd("HIGH"),
        walk_minutes=10,
        preferences=PlanningPreferences(
            interests=frozenset({"education"}),
            companion_type="family",
            fitness_level="low",
            accessible=True,
            crowd_avoidance=False,
        ),
    )

    assert scored.breakdown == {
        "base": 50,
        "interest": 30,
        "crowd": -5,
        "distance": -20,
        "companion": 15,
        "fitness": -13,
        "accessibility": 20,
    }
    assert scored.score == 77
    assert scored.explanation[-1] == "轮椅无障碍适配 (+20)"

    inaccessible = RulesPlanner().score_candidate(
        attraction=_attraction(tags=["restful"]),
        crowd=_crowd("MEDIUM"),
        walk_minutes=1,
        preferences=PlanningPreferences(
            interests=frozenset(),
            companion_type="senior",
            fitness_level="medium",
            accessible=True,
        ),
    )
    assert inaccessible.breakdown["companion"] == 15
    assert inaccessible.breakdown["accessibility"] == -10_000


@pytest.mark.parametrize(
    ("companion", "tags", "fitness", "expected_companion", "expected_fitness"),
    [
        ("friends", ["photo", "nature"], "high", 10, 12),
        ("solo", ["family"], "medium", 0, 0),
        ("senior", ["museum"], "medium", 0, 0),
    ],
)
def test_rules_planner_companion_and_fitness_edges(
    companion: str,
    tags: list[str],
    fitness: str,
    expected_companion: int,
    expected_fitness: int,
) -> None:
    scored = RulesPlanner().score_candidate(
        attraction=_attraction(tags=tags),
        crowd=_crowd("LOW"),
        walk_minutes=2,
        preferences=PlanningPreferences(
            interests=frozenset(),
            companion_type=companion,
            fitness_level=fitness,
            accessible=False,
        ),
    )

    assert scored.breakdown["crowd"] == 20
    assert scored.breakdown["companion"] == expected_companion
    assert scored.breakdown["fitness"] == expected_fitness
    assert scored.breakdown["accessibility"] == 0


def _route_node(code: str, *, accessible: bool = True) -> RouteNode:
    return RouteNode(
        id=uuid4(),
        code=code,
        name=code,
        kind="junction",
        x=0,
        y=0,
        accessible=accessible,
    )


def _route_edge(
    origin: RouteNode,
    destination: RouteNode,
    *,
    wheelchair_ok: bool = True,
    stroller_ok: bool = True,
    bidirectional: bool = False,
) -> RouteEdge:
    return RouteEdge(
        id=uuid4(),
        from_node_id=origin.id,
        to_node_id=destination.id,
        walk_minutes=3,
        distance_meters=180,
        accessible=True,
        wheelchair_ok=wheelchair_ok,
        stroller_ok=stroller_ok,
        bidirectional=bidirectional,
    )


def _session_with(*scalar_results: list[object]) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = list(scalar_results)
    return session


@pytest.mark.asyncio
async def test_schematic_map_rejects_missing_inaccessible_and_filtered_paths() -> None:
    provider = SchematicMapProvider()
    origin = _route_node("origin")
    destination = _route_node("destination")

    with pytest.raises(NoSchematicRouteError, match="起点或终点不在"):
        await provider.route(
            _session_with([origin]),
            from_node_id=origin.id,
            to_node_id=destination.id,
            wheelchair=False,
            stroller=False,
        )

    inaccessible = _route_node("stairs", accessible=False)
    with pytest.raises(NoSchematicRouteError, match="无法通行路线起点或终点"):
        await provider.route(
            _session_with([origin, inaccessible]),
            from_node_id=origin.id,
            to_node_id=inaccessible.id,
            wheelchair=True,
            stroller=False,
        )

    blocked_edge = _route_edge(origin, destination, stroller_ok=False)
    with pytest.raises(NoSchematicRouteError, match="没有符合无障碍要求"):
        await provider.route(
            _session_with([origin, destination], [blocked_edge]),
            from_node_id=origin.id,
            to_node_id=destination.id,
            wheelchair=False,
            stroller=True,
        )


@pytest.mark.asyncio
async def test_schematic_map_respects_one_way_accessible_edges() -> None:
    provider = SchematicMapProvider()
    origin = _route_node("origin")
    destination = _route_node("destination")
    edge = _route_edge(origin, destination)

    route = await provider.route(
        _session_with([origin, destination], [edge]),
        from_node_id=origin.id,
        to_node_id=destination.id,
        wheelchair=True,
        stroller=True,
    )
    assert route.node_ids == [origin.id, destination.id]
    assert route.edge_ids == [edge.id]
    assert route.explanation[-1] == "已应用: 轮椅可通行路段、婴儿车可通行路段"

    with pytest.raises(NoSchematicRouteError, match="没有符合无障碍要求"):
        await provider.route(
            _session_with([origin, destination], [edge]),
            from_node_id=destination.id,
            to_node_id=origin.id,
            wheelchair=False,
            stroller=False,
        )


def _ticket_slot(
    visit_date: date,
    *,
    capacity: int = 10,
    reserved: int = 0,
    sold: int = 0,
) -> TicketSlot:
    ticket_type = TicketType(
        id=uuid4(),
        code=f"type-{uuid4().hex[:8]}",
        name="成人票",
        audience="成人",
        description="质量边界测试",
        base_price_cents=10_000,
        admission_count=1,
        is_active=True,
    )
    slot = TicketSlot(
        id=uuid4(),
        ticket_type_id=ticket_type.id,
        visit_date=visit_date,
        start_time=time(9),
        end_time=time(10),
        is_active=True,
    )
    slot.ticket_type = ticket_type
    slot.inventory = TicketInventory(
        slot_id=slot.id,
        capacity=capacity,
        reserved=reserved,
        sold=sold,
        version=1,
    )
    return slot


def _price_rule(
    name: str,
    adjustment_bps: int,
    *,
    weekend_only: bool = False,
    min_occupancy_bps: int | None = None,
) -> DynamicPriceRule:
    return DynamicPriceRule(
        id=uuid4(),
        name=name,
        ticket_type_id=None,
        rule_type="quality",
        adjustment_bps=adjustment_bps,
        weekend_only=weekend_only,
        min_occupancy_bps=min_occupancy_bps,
        priority=1,
        starts_on=None,
        ends_on=None,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_ticket_pricing_skips_inapplicable_rules_and_never_goes_negative() -> None:
    weekday = date(2030, 1, 7)
    while weekday.weekday() >= 5:
        weekday += timedelta(days=1)
    slot = _ticket_slot(weekday, reserved=5)
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = [
        _price_rule("周末规则", 1_000, weekend_only=True),
        _price_rule("高占用规则", 2_000, min_occupancy_bps=9_000),
        _price_rule("组合优惠一", -6_000),
        _price_rule("组合优惠二", -6_000),
    ]

    unit_price, explanation = await ticketing.calculate_unit_price(session, slot)

    assert unit_price == 0
    assert not any("周末规则" in item for item in explanation)
    assert not any("高占用规则" in item for item in explanation)
    assert any("组合优惠一" in item for item in explanation)

    session.scalar.return_value = slot
    with pytest.raises(AppError) as insufficient:
        await ticketing.quote_ticket_order(
            session,
            slot_id=slot.id,
            quantity=6,
            settings=Settings(app_env="test"),
        )
    assert insufficient.value.code == "INSUFFICIENT_INVENTORY"


@pytest.mark.asyncio
async def test_gate_validation_rejects_bad_missing_and_out_of_window_credentials() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret_key="quality-edge-jwt-secret-1234567890",
    )
    validator = User(
        id=uuid4(),
        username="gate-validator",
        display_name="Gate Validator",
        password_hash="unused",
        is_active=True,
    )

    invalid_session = AsyncMock(spec=AsyncSession)
    invalid_session.scalar.return_value = None
    with pytest.raises(AppError) as invalid:
        await ticketing.validate_ticket_at_gate(
            invalid_session,
            qr_data="not-a-ticket-credential",
            request_id="quality-gate-invalid",
            gate_code="north",
            validator=validator,
            settings=settings,
        )
    assert invalid.value.code == "INVALID_QR"

    ticket_id = uuid4()
    slot_id = uuid4()
    qr_data, _ = create_ticket_qr(
        ticket_id=ticket_id,
        ticket_version=1,
        slot_id=slot_id,
        settings=settings,
    )
    missing_session = AsyncMock(spec=AsyncSession)
    missing_session.scalar.side_effect = [None, None]
    with pytest.raises(AppError) as missing:
        await ticketing.validate_ticket_at_gate(
            missing_session,
            qr_data=qr_data,
            request_id="quality-gate-missing",
            gate_code="north",
            validator=validator,
            settings=settings,
        )
    assert missing.value.code == "TICKET_NOT_FOUND"

    future_slot = _ticket_slot(datetime.now(UTC).date() + timedelta(days=30))
    order = TicketOrder(
        id=uuid4(),
        order_no="QUALITY-ORDER",
        user_id=uuid4(),
        status=ORDER_PAID,
        total_cents=10_000,
        idempotency_key="quality-order-key",
        request_hash="0" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        version=1,
    )
    ticket = ElectronicTicket(
        id=ticket_id,
        order_id=order.id,
        order_item_id=uuid4(),
        slot_id=future_slot.id,
        user_id=order.user_id,
        ticket_code="QUALITY-TICKET",
        status="ISSUED",
        version=1,
    )
    ticket.order = order
    ticket.slot = future_slot
    future_qr, _ = create_ticket_qr(
        ticket_id=ticket.id,
        ticket_version=ticket.version,
        slot_id=ticket.slot_id,
        settings=settings,
    )
    outside_session = AsyncMock(spec=AsyncSession)
    outside_session.scalar.side_effect = [None, ticket]
    with pytest.raises(AppError) as outside:
        await ticketing.validate_ticket_at_gate(
            outside_session,
            qr_data=future_qr,
            request_id="quality-gate-future",
            gate_code="north",
            validator=validator,
            settings=settings,
        )
    assert outside.value.code == "TICKET_OUTSIDE_VALIDATION_WINDOW"


def _hospitality_offer(kind: str = "ROOM") -> HospitalityOffer:
    return HospitalityOffer(
        id=uuid4(),
        venue_id=uuid4(),
        code=f"offer-{uuid4().hex[:8]}",
        kind=kind,
        name="测试住宿",
        description="质量边界测试",
        unit_price_cents=20_000,
        capacity_per_bucket=4,
        max_party_size=2,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_hospitality_rejects_kind_range_party_and_inventory_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    offer_id = uuid4()
    session.scalar.return_value = None
    with pytest.raises(AppError) as missing:
        await hospitality._get_offer(session, offer_id=offer_id, expected_kind="ROOM")
    assert missing.value.code == "OFFER_NOT_FOUND"

    session.scalar.return_value = _hospitality_offer("MEAL")
    with pytest.raises(AppError) as wrong_kind:
        await hospitality._get_offer(session, offer_id=offer_id, expected_kind="ROOM")
    assert wrong_kind.value.code == "OFFER_KIND_MISMATCH"

    offer = _hospitality_offer()
    monkeypatch.setattr(hospitality, "_get_offer", AsyncMock(return_value=offer))
    user = SimpleNamespace(id=uuid4(), role_names=["tourist"])
    future = datetime.now(UTC).date() + timedelta(days=30)
    common = {
        "session": session,
        "user": user,
        "offer_id": offer.id,
        "quantity": 1,
        "idempotency_key": "quality-stay-key",
        "settings": Settings(app_env="test"),
    }
    with pytest.raises(AppError) as invalid_range:
        await hospitality.book_stay(
            **common,
            check_in=future,
            check_out=future,
            party_size=1,
        )
    assert invalid_range.value.code == "INVALID_STAY_RANGE"

    with pytest.raises(AppError) as party:
        await hospitality.book_stay(
            **common,
            check_in=future,
            check_out=future + timedelta(days=1),
            party_size=3,
        )
    assert party.value.code == "PARTY_TOO_LARGE"

    session.scalars.return_value = []
    with pytest.raises(AppError) as inventory:
        await hospitality.book_stay(
            **common,
            check_in=future,
            check_out=future + timedelta(days=1),
            party_size=2,
        )
    assert inventory.value.code == "INVENTORY_UNAVAILABLE"

    with pytest.raises(AppError) as date_range:
        await hospitality.list_availability(
            session,
            resource_id=offer.id,
            date_from=future,
            date_to=future + timedelta(days=32),
        )
    assert date_range.value.code == "INVALID_DATE_RANGE"


@pytest.mark.asyncio
async def test_points_redemption_rolls_back_missing_sold_out_and_insufficient_rewards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    reward_id = uuid4()
    common = {
        "user": user,
        "reward_id": reward_id,
        "quantity": 2,
        "idempotency_key": "quality-redemption-key",
    }
    monkeypatch.setattr(points, "_lock_point_account", AsyncMock())

    replay_session = AsyncMock(spec=AsyncSession)
    replay_session.scalar.return_value = Redemption(request_hash="different")
    with pytest.raises(AppError) as conflict:
        await points.redeem_reward(replay_session, **common)
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"

    missing_session = AsyncMock(spec=AsyncSession)
    missing_session.scalar.side_effect = [None, None]
    missing_session.get.return_value = None
    with pytest.raises(AppError) as missing:
        await points.redeem_reward(missing_session, **common)
    assert missing.value.code == "REWARD_NOT_FOUND"
    missing_session.rollback.assert_awaited_once()

    reward = Reward(
        id=reward_id,
        code="quality-reward",
        name="测试奖励",
        description="质量边界测试",
        points_cost=100,
        stock=1,
        is_active=True,
        is_demo=True,
        version=1,
    )
    sold_out_session = AsyncMock(spec=AsyncSession)
    sold_out_session.scalar.side_effect = [None, None]
    sold_out_session.get.return_value = reward
    sold_out_session.execute.return_value = SimpleNamespace(rowcount=0)
    with pytest.raises(AppError) as sold_out:
        await points.redeem_reward(sold_out_session, **common)
    assert sold_out.value.code == "REWARD_SOLD_OUT"
    sold_out_session.rollback.assert_awaited_once()

    debit_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    insufficient_session = AsyncMock(spec=AsyncSession)
    insufficient_session.scalar.side_effect = [None, None]
    insufficient_session.get.return_value = reward
    insufficient_session.execute.side_effect = [
        SimpleNamespace(rowcount=1),
        debit_result,
    ]
    with pytest.raises(AppError) as insufficient:
        await points.redeem_reward(insufficient_session, **common)
    assert insufficient.value.code == "INSUFFICIENT_POINTS"
    insufficient_session.rollback.assert_awaited_once()

    with pytest.raises(ValueError, match="positive"):
        await points.award_points(
            AsyncMock(spec=AsyncSession),
            user_id=user.id,
            points=0,
            source_type="QUALITY",
            source_id=uuid4(),
            description="invalid",
        )


@pytest.mark.asyncio
async def test_commerce_campaign_and_cart_guards_use_authoritative_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    product = SimpleNamespace(id=uuid4(), category_id=uuid4(), price_cents=10_000)
    campaigns = [
        Campaign(
            id=uuid4(),
            code="expired",
            name="已结束",
            description="expired",
            product_id=product.id,
            category_id=None,
            discount_bps=5_000,
            starts_at=now - timedelta(days=2),
            ends_at=now - timedelta(days=1),
            is_active=True,
        ),
        Campaign(
            id=uuid4(),
            code="current-low",
            name="当前折扣",
            description="active",
            product_id=None,
            category_id=product.category_id,
            discount_bps=1_000,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
            is_active=True,
        ),
        Campaign(
            id=uuid4(),
            code="current-high",
            name="最优折扣",
            description="active",
            product_id=product.id,
            category_id=None,
            discount_bps=2_000,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
            is_active=True,
        ),
    ]
    price_session = AsyncMock(spec=AsyncSession)
    price_session.scalars.return_value = campaigns
    effective, campaign = await commerce.authoritative_price(price_session, product)
    assert effective == 8_000
    assert campaign is campaigns[2]

    monkeypatch.setattr(commerce, "expire_shop_orders", AsyncMock(return_value=0))
    cart = SimpleNamespace(id=uuid4(), items=[], version=1)
    monkeypatch.setattr(commerce, "_ensure_cart", AsyncMock(return_value=cart))
    user = SimpleNamespace(id=uuid4())
    cart_product = SimpleNamespace(
        id=uuid4(),
        inventory=SimpleNamespace(stock=1),
    )
    cart_session = AsyncMock(spec=AsyncSession)
    cart_session.scalar.return_value = cart_product
    with pytest.raises(AppError) as stock:
        await commerce.add_cart_item(
            cart_session,
            user=user,
            product_id=cart_product.id,
            quantity=2,
        )
    assert stock.value.code == "INSUFFICIENT_STOCK"

    existing = SimpleNamespace(product_id=cart_product.id, quantity=99)
    cart.items = [existing]
    with pytest.raises(AppError) as limit:
        await commerce.add_cart_item(
            cart_session,
            user=user,
            product_id=cart_product.id,
            quantity=1,
        )
    assert limit.value.code == "CART_QUANTITY_LIMIT"


@pytest.mark.asyncio
async def test_reservation_group_and_itinerary_integrity_guards() -> None:
    allocation = SimpleNamespace(bucket_id=uuid4(), quantity=2, status=RESERVATION_HELD)
    reservation = SimpleNamespace(allocations=[allocation])
    inconsistent_session = AsyncMock(spec=AsyncSession)
    inconsistent_session.execute.return_value = SimpleNamespace(rowcount=0)
    with pytest.raises(RuntimeError, match="ledger is inconsistent"):
        await reservations._release_allocations(
            inconsistent_session,
            reservation,
            source_status=RESERVATION_HELD,
            target_status=RESERVATION_EXPIRED,
        )

    user = SimpleNamespace(id=uuid4(), role_names=[])
    group_session = AsyncMock(spec=AsyncSession)
    group_session.scalar.return_value = None
    with pytest.raises(AppError) as hidden_group:
        await groups.accessible_group(group_session, group_id=uuid4(), user=user)
    assert hidden_group.value.code == "GROUP_NOT_FOUND"

    itinerary_session = AsyncMock(spec=AsyncSession)
    itinerary_session.scalar.return_value = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
    )
    with pytest.raises(AppError) as hidden_itinerary:
        await itinerary._owned_itinerary(
            itinerary_session,
            itinerary_id=uuid4(),
            user=user,
        )
    assert hidden_itinerary.value.code == "ITINERARY_NOT_FOUND"

    visit_date = date(2030, 1, 2)
    first_slot = SimpleNamespace(
        visit_date=visit_date,
        start_time=time(9),
        end_time=time(10),
    )
    second_slot = SimpleNamespace(
        visit_date=visit_date,
        start_time=time(9, 30),
        end_time=time(10, 30),
    )
    orders = [
        SimpleNamespace(
            id=uuid4(),
            items=[SimpleNamespace(slot=first_slot, ticket_type_name="成人票")],
        ),
        SimpleNamespace(
            id=uuid4(),
            items=[SimpleNamespace(slot=second_slot, ticket_type_name="演出票")],
        ),
    ]
    commitment_session = AsyncMock(spec=AsyncSession)
    commitment_session.scalars.return_value = orders
    with pytest.raises(AppError) as conflict:
        await itinerary._ticket_commitments(
            commitment_session,
            user_id=user.id,
            visit_date=visit_date,
        )
    assert conflict.value.code == "MANDATORY_COMMITMENT_CONFLICT"


@pytest.mark.asyncio
async def test_auth_dependency_rejects_missing_malformed_and_stale_subjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        app_env="test",
        jwt_secret_key="quality-edge-jwt-secret-1234567890",
        log_level="CRITICAL",
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    session = AsyncMock(spec=AsyncSession)

    for credentials in (
        None,
        HTTPAuthorizationCredentials(scheme="Basic", credentials="value"),
    ):
        with pytest.raises(AppError) as missing:
            await auth_dependencies.get_current_user(request, credentials, session)
        assert missing.value.code == "NOT_AUTHENTICATED"

    with pytest.raises(AppError) as malformed:
        await auth_dependencies.get_current_user(
            request,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"),
            session,
        )
    assert malformed.value.code == "INVALID_ACCESS_TOKEN"

    user_id = uuid4()
    token, _ = create_access_token(user_id, ["tourist"], settings)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    inactive = User(
        id=user_id,
        username="inactive",
        display_name="Inactive",
        password_hash="unused",
        is_active=False,
    )
    lookup = AsyncMock(side_effect=[None, inactive])
    monkeypatch.setattr(auth_dependencies, "get_user_by_id", lookup)
    for _ in range(2):
        with pytest.raises(AppError) as stale:
            await auth_dependencies.get_current_user(request, credentials, session)
        assert stale.value.code == "INVALID_ACCESS_TOKEN"

    assert verify_password("secret", "not-an-argon2-hash") is False
    assert password_needs_rehash("not-an-argon2-hash") is True


def test_error_handlers_keep_headers_and_structured_http_details(
    application: FastAPI,
) -> None:
    @application.get("/quality/app-error")
    async def app_error() -> None:
        raise AppError(
            status_code=409,
            code="QUALITY_CONFLICT",
            message="Quality conflict",
            headers={"X-Recovery": "retry"},
        )

    @application.get("/quality/http-detail")
    async def http_detail() -> None:
        raise HTTPException(status_code=400, detail={"field": "invalid"})

    @application.get("/quality/custom-http")
    async def custom_http() -> None:
        raise HTTPException(status_code=499, detail="Client closed request")

    with TestClient(application) as client:
        domain = client.get("/quality/app-error")
        structured = client.get("/quality/http-detail")
        custom = client.get("/quality/custom-http")

    assert domain.status_code == 409
    assert domain.headers["X-Recovery"] == "retry"
    assert structured.json()["error"] == {
        "code": "BAD_REQUEST",
        "message": "Bad Request",
        "details": {"field": "invalid"},
    }
    assert custom.status_code == 499
    assert custom.json()["error"] == {
        "code": "HTTP_499",
        "message": "Client closed request",
    }

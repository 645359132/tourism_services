"""Transactional ticketing use cases and inventory state transitions."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import jwt
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import create_ticket_qr, create_ticket_quote, decode_token
from app.db.models.ticketing import (
    ORDER_CANCELLED,
    ORDER_EXPIRED,
    ORDER_PAID,
    ORDER_PENDING_PAYMENT,
    ORDER_REFUNDED,
    TICKET_ISSUED,
    TICKET_USED,
    TICKET_VOID,
    DynamicPriceRule,
    ElectronicTicket,
    RefundRequest,
    RescheduleRequest,
    TicketInventory,
    TicketOrder,
    TicketOrderItem,
    TicketSlot,
    TicketType,
    TicketValidation,
)
from app.db.models.user import User
from app.providers.gate import DemoFaceGateProvider, FaceDemoSample, FaceGateProvider
from app.providers.payment import DemoPaymentProvider
from app.schemas.ticketing import (
    FaceDemoVerifyResponse,
    GateValidationResponse,
    QuoteResponse,
    TicketOrderResponse,
    TicketQrResponse,
    TicketSlotItem,
    TicketSummary,
    TicketTypeItem,
)
from app.services.reservations import (
    acquire_user_schedule_lock,
    expire_reservation_holds,
)

SCENIC_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _is_admin(user: User) -> bool:
    return "admin" in user.role_names


def _scenic_today() -> date:
    return datetime.now(SCENIC_TIMEZONE).date()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _slot_start_utc(slot: TicketSlot) -> datetime:
    return datetime.combine(
        slot.visit_date,
        slot.start_time,
        tzinfo=SCENIC_TIMEZONE,
    ).astimezone(UTC)


def _slot_end_utc(slot: TicketSlot) -> datetime:
    end = datetime.combine(
        slot.visit_date,
        slot.end_time,
        tzinfo=SCENIC_TIMEZONE,
    ).astimezone(UTC)
    if slot.end_time <= slot.start_time:
        end += timedelta(days=1)
    return end


def _refund_deadline_utc(slot: TicketSlot, cutoff_hours: int) -> datetime:
    return _slot_start_utc(slot) - timedelta(hours=cutoff_hours)


def _order_statement():
    return (
        select(TicketOrder)
        .options(
            selectinload(TicketOrder.items).joinedload(TicketOrderItem.slot),
            selectinload(TicketOrder.tickets),
        )
        .execution_options(populate_existing=True)
    )


async def _load_order(session: AsyncSession, order_id: UUID) -> TicketOrder | None:
    return await session.scalar(_order_statement().where(TicketOrder.id == order_id))


async def _owned_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
) -> TicketOrder:
    return await _owned_order_by_identity(
        session,
        order_id=order_id,
        user_id=user.id,
        admin=_is_admin(user),
    )


async def _owned_order_by_identity(
    session: AsyncSession,
    *,
    order_id: UUID,
    user_id: UUID,
    admin: bool,
) -> TicketOrder:
    order = await _load_order(session, order_id)
    if order is None or (order.user_id != user_id and not admin):
        raise _error(404, "ORDER_NOT_FOUND", "Ticket order not found")
    return order


def order_response(
    order: TicketOrder,
    *,
    refund_cutoff_hours: int,
) -> TicketOrderResponse:
    if len(order.items) != 1:
        raise RuntimeError("MVP ticket orders must contain exactly one item")
    item = order.items[0]
    slot = item.slot
    tickets = sorted(order.tickets, key=lambda ticket: (ticket.issued_at, ticket.ticket_code))
    refund_deadline = _refund_deadline_utc(slot, refund_cutoff_hours)
    issued_count = sum(ticket.status == TICKET_ISSUED for ticket in tickets)
    refundable = (
        order.status == ORDER_PAID
        and issued_count == item.quantity
        and datetime.now(UTC) < refund_deadline
    )
    return TicketOrderResponse(
        id=str(order.id),
        order_no=order.order_no,
        status=order.status,
        ticket_type_name=item.ticket_type_name,
        slot_id=str(item.slot_id),
        visit_date=slot.visit_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        quantity=item.quantity,
        unit_price_cents=item.unit_price_cents,
        total_cents=order.total_cents,
        # SQLite 会丢失 datetime 的 tzinfo; 统一在 API 边界补回 UTC, 避免客户端把 UTC 当成本地时间.
        expires_at=_aware(order.expires_at),
        refund_cutoff_hours=refund_cutoff_hours,
        refund_deadline_at=refund_deadline,
        refundable=refundable,
        tickets=[
            TicketSummary(
                id=str(ticket.id),
                ticket_code=ticket.ticket_code,
                status=ticket.status,
            )
            for ticket in tickets
        ],
    )


async def list_ticket_types(session: AsyncSession) -> list[TicketTypeItem]:
    ticket_types = list(
        await session.scalars(
            select(TicketType).where(TicketType.is_active.is_(True)).order_by(TicketType.code)
        )
    )
    return [
        TicketTypeItem(
            id=str(ticket_type.id),
            code=ticket_type.code,
            name=ticket_type.name,
            audience=ticket_type.audience,
            description=ticket_type.description,
            base_price_cents=ticket_type.base_price_cents,
        )
        for ticket_type in ticket_types
    ]


async def _get_slot(session: AsyncSession, slot_id: UUID) -> TicketSlot:
    slot = await session.scalar(select(TicketSlot).where(TicketSlot.id == slot_id))
    if slot is None or not slot.is_active or not slot.ticket_type.is_active:
        raise _error(404, "SLOT_NOT_FOUND", "Ticket slot not found")
    if slot.inventory is None:
        raise _error(500, "INVENTORY_MISSING", "Ticket inventory is not configured")
    return slot


async def calculate_unit_price(
    session: AsyncSession,
    slot: TicketSlot,
) -> tuple[int, list[str]]:
    inventory = slot.inventory
    occupancy_bps = (
        ((inventory.reserved + inventory.sold) * 10_000) // inventory.capacity
        if inventory.capacity > 0
        else 10_000
    )
    rules = list(
        await session.scalars(
            select(DynamicPriceRule)
            .where(
                DynamicPriceRule.is_active.is_(True),
                or_(
                    DynamicPriceRule.ticket_type_id.is_(None),
                    DynamicPriceRule.ticket_type_id == slot.ticket_type_id,
                ),
                or_(
                    DynamicPriceRule.starts_on.is_(None),
                    DynamicPriceRule.starts_on <= slot.visit_date,
                ),
                or_(
                    DynamicPriceRule.ends_on.is_(None),
                    DynamicPriceRule.ends_on >= slot.visit_date,
                ),
            )
            .order_by(DynamicPriceRule.priority, DynamicPriceRule.name)
        )
    )

    adjustment_bps = 0
    explanation = [f"Base price {slot.ticket_type.base_price_cents} cents"]
    for rule in rules:
        if rule.weekend_only and slot.visit_date.weekday() < 5:
            continue
        if rule.min_occupancy_bps is not None and occupancy_bps < rule.min_occupancy_bps:
            continue
        adjustment_bps += rule.adjustment_bps
        sign = "+" if rule.adjustment_bps >= 0 else ""
        explanation.append(f"{rule.name}: {sign}{rule.adjustment_bps / 100:.0f}%")

    unit_price = max(
        0,
        (slot.ticket_type.base_price_cents * (10_000 + adjustment_bps) + 5_000) // 10_000,
    )
    return unit_price, explanation


async def list_ticket_slots(
    session: AsyncSession,
    *,
    visit_date: date,
    ticket_type_id: UUID | None,
) -> list[TicketSlotItem]:
    statement = (
        select(TicketSlot)
        .where(TicketSlot.visit_date == visit_date, TicketSlot.is_active.is_(True))
        .order_by(TicketSlot.start_time, TicketSlot.ticket_type_id)
    )
    if ticket_type_id is not None:
        statement = statement.where(TicketSlot.ticket_type_id == ticket_type_id)
    slots = list(await session.scalars(statement))
    items: list[TicketSlotItem] = []
    for slot in slots:
        unit_price, explanation = await calculate_unit_price(session, slot)
        inventory = slot.inventory
        items.append(
            TicketSlotItem(
                id=str(slot.id),
                ticket_type_id=str(slot.ticket_type_id),
                visit_date=slot.visit_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                capacity=inventory.capacity,
                remaining=inventory.capacity - inventory.reserved - inventory.sold,
                unit_price_cents=unit_price,
                pricing_explanation=explanation,
            )
        )
    return items


async def quote_ticket_order(
    session: AsyncSession,
    *,
    slot_id: UUID,
    quantity: int,
    settings: Settings,
) -> QuoteResponse:
    slot = await _get_slot(session, slot_id)
    remaining = slot.inventory.capacity - slot.inventory.reserved - slot.inventory.sold
    if quantity > remaining:
        raise _error(409, "INSUFFICIENT_INVENTORY", "Not enough ticket inventory")
    unit_price, explanation = await calculate_unit_price(session, slot)
    quote_token, expires_at, quote_id = create_ticket_quote(
        slot_id=slot.id,
        quantity=quantity,
        unit_price_cents=unit_price,
        settings=settings,
    )
    return QuoteResponse(
        id=quote_id,
        slot_id=str(slot.id),
        ticket_type_id=str(slot.ticket_type_id),
        visit_date=slot.visit_date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        quantity=quantity,
        unit_price_cents=unit_price,
        total_cents=unit_price * quantity,
        expires_at=expires_at,
        quote_token=quote_token,
        pricing_explanation=explanation,
    )


def _validated_quote_unit_price(
    *,
    quote_token: str,
    slot_id: UUID,
    quantity: int,
    settings: Settings,
) -> int:
    try:
        claims = decode_token(
            quote_token,
            expected_type="ticket_quote",
            settings=settings,
        )
    except jwt.ExpiredSignatureError as exc:
        raise _error(409, "QUOTE_EXPIRED", "Ticket quote has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _error(422, "INVALID_QUOTE", "Ticket quote token is invalid") from exc
    unit_price = claims.get("unit_price_cents")
    if (
        claims.get("purpose") != "ticket_purchase"
        or claims.get("sub") != str(slot_id)
        or claims.get("quantity") != quantity
        or type(unit_price) is not int
        or unit_price < 0
    ):
        raise _error(409, "QUOTE_MISMATCH", "Ticket quote does not match this order")
    return unit_price


async def expire_pending_orders(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
) -> int:
    now = datetime.now(UTC)
    statement = _order_statement().where(
        TicketOrder.status == ORDER_PENDING_PAYMENT,
        TicketOrder.expires_at <= now,
    )
    if user_id is not None:
        statement = statement.where(TicketOrder.user_id == user_id)
    statement = statement.limit(100)
    orders = list(await session.scalars(statement))
    expired_count = 0
    for order in orders:
        item = order.items[0]
        result = await session.execute(
            update(TicketOrder)
            .execution_options(synchronize_session=False)
            .where(
                TicketOrder.id == order.id,
                TicketOrder.status == ORDER_PENDING_PAYMENT,
                TicketOrder.version == order.version,
                TicketOrder.expires_at <= now,
            )
            .values(status=ORDER_EXPIRED, version=TicketOrder.version + 1)
        )
        if result.rowcount != 1:
            continue
        released = await session.execute(
            update(TicketInventory)
            .execution_options(synchronize_session=False)
            .where(
                TicketInventory.slot_id == item.slot_id,
                TicketInventory.reserved >= item.quantity,
            )
            .values(
                reserved=TicketInventory.reserved - item.quantity,
                version=TicketInventory.version + 1,
            )
        )
        if released.rowcount != 1:
            raise RuntimeError("Expired order inventory ledger is inconsistent")
        expired_count += 1
    return expired_count


async def create_ticket_order(
    session: AsyncSession,
    *,
    user: User,
    slot_id: UUID,
    quantity: int,
    quote_token: str,
    idempotency_key: str,
    settings: Settings,
) -> TicketOrder:
    actor_id = user.id
    await expire_pending_orders(session)
    await session.commit()
    request_hash = _hash_payload(
        {
            "quantity": quantity,
            "slot_id": str(slot_id),
        }
    )
    existing = await session.scalar(
        select(TicketOrder).where(
            TicketOrder.user_id == actor_id,
            TicketOrder.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Idempotency key payload differs")
        await session.commit()
        loaded = await _load_order(session, existing.id)
        assert loaded is not None
        return loaded

    slot = await _get_slot(session, slot_id)
    if slot.visit_date < _scenic_today():
        raise _error(409, "SLOT_CLOSED", "Ticket slot is no longer available")
    # 同一 slot coordination lock 内验签并兑现签名价格, 库存仍以当前账本为准。
    unit_price = _validated_quote_unit_price(
        quote_token=quote_token,
        slot_id=slot_id,
        quantity=quantity,
        settings=settings,
    )
    await acquire_user_schedule_lock(session, actor_id)
    # 跨资源冲突判断和过期预约释放必须处于同一用户时程锁事务中。
    await expire_reservation_holds(session, user_id=actor_id)
    existing = await session.scalar(
        select(TicketOrder).where(
            TicketOrder.user_id == actor_id,
            TicketOrder.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            await session.rollback()
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Idempotency key payload differs")
        order_id = existing.id
        await session.rollback()
        loaded = await _load_order(session, order_id)
        assert loaded is not None
        return loaded
    # 门票时段表达“可入园窗口”; 它不是会独占游客时间的园内活动。游客理应能先约演出
    # 再买覆盖该时段的门票; 因此这里只校验场次有效性与共享库存; 不做日程互斥。
    reserved = await session.execute(
        update(TicketInventory)
        .execution_options(synchronize_session=False)
        .where(
            TicketInventory.slot_id == slot.id,
            TicketInventory.capacity - TicketInventory.reserved - TicketInventory.sold >= quantity,
        )
        .values(
            reserved=TicketInventory.reserved + quantity,
            version=TicketInventory.version + 1,
        )
    )
    if reserved.rowcount != 1:
        raise _error(409, "INSUFFICIENT_INVENTORY", "Not enough ticket inventory")

    order_id = uuid4()
    order = TicketOrder(
        id=order_id,
        order_no=f"TO-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}",
        user_id=actor_id,
        status=ORDER_PENDING_PAYMENT,
        total_cents=unit_price * quantity,
        currency="CNY",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.ticket_order_reservation_minutes),
    )
    order.items.append(
        TicketOrderItem(
            slot_id=slot.id,
            ticket_type_id=slot.ticket_type_id,
            ticket_type_name=slot.ticket_type.name,
            quantity=quantity,
            unit_price_cents=unit_price,
            line_total_cents=unit_price * quantity,
        )
    )
    session.add(order)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(TicketOrder).where(
                TicketOrder.user_id == actor_id,
                TicketOrder.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(
                409,
                "IDEMPOTENCY_CONFLICT",
                "Idempotency key payload differs",
            ) from exc
        order_id = concurrent.id

    loaded = await _load_order(session, order_id)
    assert loaded is not None
    return loaded


async def list_ticket_orders(
    session: AsyncSession,
    *,
    user: User,
    offset: int,
    limit: int,
) -> tuple[list[TicketOrder], int]:
    await expire_pending_orders(session, user_id=None if _is_admin(user) else user.id)
    await session.commit()
    statement = _order_statement().order_by(
        TicketOrder.created_at.desc(),
        TicketOrder.id.desc(),
    )
    if not _is_admin(user):
        statement = statement.where(TicketOrder.user_id == user.id)
    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    return list(await session.scalars(statement.offset(offset).limit(limit))), total


async def get_ticket_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
) -> TicketOrder:
    await expire_pending_orders(session, user_id=None if _is_admin(user) else user.id)
    await session.commit()
    return await _owned_order(session, order_id=order_id, user=user)


def _new_ticket(
    *,
    order: TicketOrder,
    item: TicketOrderItem,
    slot_id: UUID,
) -> ElectronicTicket:
    return ElectronicTicket(
        order_id=order.id,
        order_item_id=item.id,
        slot_id=slot_id,
        user_id=order.user_id,
        ticket_code=f"TKT-{uuid4().hex[:20].upper()}",
        status=TICKET_ISSUED,
    )


async def pay_ticket_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
    idempotency_key: str,
    payment_provider: DemoPaymentProvider | None = None,
) -> TicketOrder:
    actor_id = user.id
    actor_is_admin = _is_admin(user)
    await expire_pending_orders(session, user_id=actor_id)
    order = await _owned_order(session, order_id=order_id, user=user)
    if order.status == ORDER_PAID:
        if order.payment_idempotency_key != idempotency_key:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Payment key differs")
        await session.commit()
        return order
    if order.status != ORDER_PENDING_PAYMENT:
        raise _error(409, "ORDER_NOT_PAYABLE", "Order is not payable")

    item = order.items[0]
    provider = payment_provider or DemoPaymentProvider()
    payment = await provider.authorize(
        order_no=order.order_no,
        amount_cents=order.total_cents,
        idempotency_key=idempotency_key,
    )
    now = datetime.now(UTC)
    request_hash = _hash_payload({"amount_cents": order.total_cents, "order_id": str(order.id)})
    transitioned = await session.execute(
        update(TicketOrder)
        .execution_options(synchronize_session=False)
        .where(
            TicketOrder.id == order.id,
            TicketOrder.status == ORDER_PENDING_PAYMENT,
            TicketOrder.version == order.version,
            TicketOrder.expires_at > now,
        )
        .values(
            status=ORDER_PAID,
            paid_at=now,
            payment_idempotency_key=idempotency_key,
            payment_request_hash=request_hash,
            payment_reference=payment.reference,
            version=TicketOrder.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        concurrent = await _owned_order_by_identity(
            session,
            order_id=order_id,
            user_id=actor_id,
            admin=actor_is_admin,
        )
        if (
            concurrent.status == ORDER_PAID
            and concurrent.payment_idempotency_key == idempotency_key
        ):
            return concurrent
        raise _error(409, "ORDER_NOT_PAYABLE", "Order is not payable")

    sold = await session.execute(
        update(TicketInventory)
        .execution_options(synchronize_session=False)
        .where(
            TicketInventory.slot_id == item.slot_id,
            TicketInventory.reserved >= item.quantity,
        )
        .values(
            reserved=TicketInventory.reserved - item.quantity,
            sold=TicketInventory.sold + item.quantity,
            version=TicketInventory.version + 1,
        )
    )
    if sold.rowcount != 1:
        await session.rollback()
        raise _error(409, "INVENTORY_CONFLICT", "Reserved inventory is unavailable")

    await session.flush()
    for _ in range(item.quantity):
        session.add(_new_ticket(order=order, item=item, slot_id=item.slot_id))
    await session.commit()
    loaded = await _load_order(session, order.id)
    assert loaded is not None
    return loaded


async def cancel_pending_ticket_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
) -> TicketOrder:
    """Cancel an unpaid order once and release exactly its reserved inventory."""

    actor_id = user.id
    actor_is_admin = _is_admin(user)
    await expire_pending_orders(session, user_id=actor_id)
    await session.commit()
    order = await _owned_order(session, order_id=order_id, user=user)
    # 取消按资源状态幂等: 重放同一订单直接返回终态, 绝不能重复扣减 reserved.
    if order.status == ORDER_CANCELLED:
        return order
    if order.status != ORDER_PENDING_PAYMENT:
        raise _error(409, "ORDER_NOT_CANCELLABLE", "Only pending orders can be cancelled")

    item = order.items[0]
    transitioned = await session.execute(
        update(TicketOrder)
        .execution_options(synchronize_session=False)
        .where(
            TicketOrder.id == order.id,
            TicketOrder.status == ORDER_PENDING_PAYMENT,
            TicketOrder.version == order.version,
        )
        .values(status=ORDER_CANCELLED, version=TicketOrder.version + 1)
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        concurrent = await _owned_order_by_identity(
            session,
            order_id=order_id,
            user_id=actor_id,
            admin=actor_is_admin,
        )
        if concurrent.status == ORDER_CANCELLED:
            return concurrent
        raise _error(409, "ORDER_NOT_CANCELLABLE", "Order is not cancellable")

    # 订单状态与库存台账位于同一事务: 任一条件更新失败都会整体回滚.
    released = await session.execute(
        update(TicketInventory)
        .execution_options(synchronize_session=False)
        .where(
            TicketInventory.slot_id == item.slot_id,
            TicketInventory.reserved >= item.quantity,
        )
        .values(
            reserved=TicketInventory.reserved - item.quantity,
            version=TicketInventory.version + 1,
        )
    )
    if released.rowcount != 1:
        await session.rollback()
        raise _error(409, "INVENTORY_CONFLICT", "Reserved inventory is unavailable")

    await session.commit()
    loaded = await _load_order(session, order.id)
    assert loaded is not None
    return loaded


async def refund_ticket_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
    reason: str,
    idempotency_key: str,
    settings: Settings,
) -> TicketOrder:
    actor_id = user.id
    actor_is_admin = _is_admin(user)
    request_hash = _hash_payload({"order_id": str(order_id), "reason": reason})
    existing = await session.scalar(
        select(RefundRequest).where(
            RefundRequest.user_id == actor_id,
            RefundRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Refund key payload differs")
        order = await _owned_order(session, order_id=existing.order_id, user=user)
        return order

    order = await _owned_order(session, order_id=order_id, user=user)
    if order.status != ORDER_PAID:
        raise _error(409, "ORDER_NOT_REFUNDABLE", "Only paid orders can be refunded")
    item = order.items[0]
    refund_deadline = _refund_deadline_utc(
        item.slot,
        settings.ticket_refund_cutoff_hours,
    )
    if datetime.now(UTC) >= refund_deadline:
        raise _error(
            409,
            "REFUND_WINDOW_CLOSED",
            f"Refunds close {settings.ticket_refund_cutoff_hours} hours before the visit",
        )

    now = datetime.now(UTC)
    voided = await session.execute(
        update(ElectronicTicket)
        .execution_options(synchronize_session=False)
        .where(
            ElectronicTicket.order_id == order.id,
            ElectronicTicket.status == TICKET_ISSUED,
        )
        .values(
            status=TICKET_VOID,
            voided_at=now,
            version=ElectronicTicket.version + 1,
        )
    )
    if voided.rowcount != item.quantity:
        await session.rollback()
        concurrent = await session.scalar(
            select(RefundRequest).where(
                RefundRequest.user_id == actor_id,
                RefundRequest.idempotency_key == idempotency_key,
            )
        )
        if concurrent is not None:
            if concurrent.request_hash != request_hash:
                raise _error(409, "IDEMPOTENCY_CONFLICT", "Refund key payload differs")
            replayed = await _owned_order_by_identity(
                session,
                order_id=concurrent.order_id,
                user_id=actor_id,
                admin=actor_is_admin,
            )
            return replayed
        raise _error(409, "TICKET_ALREADY_USED", "Used or void tickets cannot be refunded")

    transitioned = await session.execute(
        update(TicketOrder)
        .execution_options(synchronize_session=False)
        .where(
            TicketOrder.id == order.id,
            TicketOrder.status == ORDER_PAID,
            TicketOrder.version == order.version,
        )
        .values(
            status=ORDER_REFUNDED,
            refunded_at=now,
            version=TicketOrder.version + 1,
        )
    )
    released = await session.execute(
        update(TicketInventory)
        .execution_options(synchronize_session=False)
        .where(
            TicketInventory.slot_id == item.slot_id,
            TicketInventory.sold >= item.quantity,
        )
        .values(
            sold=TicketInventory.sold - item.quantity,
            version=TicketInventory.version + 1,
        )
    )
    if transitioned.rowcount != 1 or released.rowcount != 1:
        await session.rollback()
        raise _error(409, "REFUND_CONFLICT", "Order changed during refund")

    session.add(
        RefundRequest(
            order_id=order.id,
            user_id=actor_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=reason,
            status="SUCCEEDED",
            processed_at=now,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(RefundRequest).where(
                RefundRequest.user_id == actor_id,
                RefundRequest.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Refund key payload differs") from exc
        replayed = await _owned_order_by_identity(
            session,
            order_id=concurrent.order_id,
            user_id=actor_id,
            admin=actor_is_admin,
        )
        return replayed
    loaded = await _load_order(session, order.id)
    assert loaded is not None
    return loaded


async def reschedule_ticket_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
    target_slot_id: UUID,
    idempotency_key: str,
) -> TicketOrder:
    actor_id = user.id
    actor_is_admin = _is_admin(user)
    request_hash = _hash_payload({"order_id": str(order_id), "target_slot_id": str(target_slot_id)})
    existing = await session.scalar(
        select(RescheduleRequest).where(
            RescheduleRequest.user_id == actor_id,
            RescheduleRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Reschedule key payload differs")
        order = await _owned_order(session, order_id=existing.order_id, user=user)
        return order

    owned_before_lock = await _owned_order_by_identity(
        session,
        order_id=order_id,
        user_id=actor_id,
        admin=actor_is_admin,
    )
    if owned_before_lock.user_id != actor_id:
        raise _error(403, "FORBIDDEN", "Cross-owner rescheduling is not permitted")
    await acquire_user_schedule_lock(session, actor_id)
    await expire_reservation_holds(session, user_id=actor_id)
    existing = await session.scalar(
        select(RescheduleRequest).where(
            RescheduleRequest.user_id == actor_id,
            RescheduleRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            await session.rollback()
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Reschedule key payload differs")
        replay_order_id = existing.order_id
        await session.rollback()
        replayed = await _owned_order_by_identity(
            session,
            order_id=replay_order_id,
            user_id=actor_id,
            admin=actor_is_admin,
        )
        return replayed

    order = await _owned_order_by_identity(
        session,
        order_id=order_id,
        user_id=actor_id,
        admin=actor_is_admin,
    )
    if order.status != ORDER_PAID:
        raise _error(409, "ORDER_NOT_RESCHEDULABLE", "Only paid orders can be rescheduled")
    item = order.items[0]
    if item.slot_id == target_slot_id:
        raise _error(409, "SAME_SLOT", "Target slot must be different")
    target = await _get_slot(session, target_slot_id)
    if target.ticket_type_id != item.ticket_type_id:
        raise _error(409, "TICKET_TYPE_MISMATCH", "Target slot ticket type differs")
    if target.visit_date < _scenic_today():
        raise _error(409, "SLOT_CLOSED", "Target slot is no longer available")
    # 改签后的门票仍是入园资格; 不应与园内演出、项目或用餐预约互斥。
    target_unit_price, _ = await calculate_unit_price(session, target)
    if target_unit_price != item.unit_price_cents:
        raise _error(
            409,
            "RESCHEDULE_PRICE_DELTA_UNSUPPORTED",
            "Target slot price differs from the paid ticket price",
        )

    occupied = await session.execute(
        update(TicketInventory)
        .execution_options(synchronize_session=False)
        .where(
            TicketInventory.slot_id == target.id,
            TicketInventory.capacity - TicketInventory.reserved - TicketInventory.sold
            >= item.quantity,
        )
        .values(
            sold=TicketInventory.sold + item.quantity,
            version=TicketInventory.version + 1,
        )
    )
    if occupied.rowcount != 1:
        raise _error(409, "INSUFFICIENT_INVENTORY", "Target slot has insufficient inventory")

    now = datetime.now(UTC)
    voided = await session.execute(
        update(ElectronicTicket)
        .execution_options(synchronize_session=False)
        .where(
            ElectronicTicket.order_id == order.id,
            ElectronicTicket.status == TICKET_ISSUED,
        )
        .values(
            status=TICKET_VOID,
            voided_at=now,
            version=ElectronicTicket.version + 1,
        )
    )
    if voided.rowcount != item.quantity:
        await session.rollback()
        concurrent = await session.scalar(
            select(RescheduleRequest).where(
                RescheduleRequest.user_id == actor_id,
                RescheduleRequest.idempotency_key == idempotency_key,
            )
        )
        if concurrent is not None:
            if concurrent.request_hash != request_hash:
                raise _error(409, "IDEMPOTENCY_CONFLICT", "Reschedule key payload differs")
            replayed = await _owned_order_by_identity(
                session,
                order_id=concurrent.order_id,
                user_id=actor_id,
                admin=actor_is_admin,
            )
            return replayed
        raise _error(409, "TICKET_ALREADY_USED", "Used or void tickets cannot be rescheduled")

    released = await session.execute(
        update(TicketInventory)
        .execution_options(synchronize_session=False)
        .where(
            TicketInventory.slot_id == item.slot_id,
            TicketInventory.sold >= item.quantity,
        )
        .values(
            sold=TicketInventory.sold - item.quantity,
            version=TicketInventory.version + 1,
        )
    )
    transitioned = await session.execute(
        update(TicketOrder)
        .execution_options(synchronize_session=False)
        .where(
            TicketOrder.id == order.id,
            TicketOrder.status == ORDER_PAID,
            TicketOrder.version == order.version,
        )
        .values(version=TicketOrder.version + 1)
    )
    if released.rowcount != 1 or transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "RESCHEDULE_CONFLICT", "Order changed during reschedule")

    source_slot_id = item.slot_id
    item.slot_id = target.id
    await session.flush()
    for _ in range(item.quantity):
        session.add(_new_ticket(order=order, item=item, slot_id=target.id))
    session.add(
        RescheduleRequest(
            order_id=order.id,
            user_id=actor_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            source_slot_id=source_slot_id,
            target_slot_id=target.id,
            status="SUCCEEDED",
            processed_at=now,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(RescheduleRequest).where(
                RescheduleRequest.user_id == actor_id,
                RescheduleRequest.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(
                409,
                "IDEMPOTENCY_CONFLICT",
                "Reschedule key payload differs",
            ) from exc
        replayed = await _owned_order_by_identity(
            session,
            order_id=concurrent.order_id,
            user_id=actor_id,
            admin=actor_is_admin,
        )
        return replayed
    loaded = await _load_order(session, order.id)
    assert loaded is not None
    return loaded


async def create_ticket_qr_response(
    session: AsyncSession,
    *,
    ticket_id: UUID,
    user: User,
    settings: Settings,
) -> TicketQrResponse:
    ticket = await session.scalar(
        select(ElectronicTicket)
        .options(joinedload(ElectronicTicket.order))
        .where(ElectronicTicket.id == ticket_id)
    )
    if ticket is None or (ticket.user_id != user.id and not _is_admin(user)):
        raise _error(404, "TICKET_NOT_FOUND", "Electronic ticket not found")
    if ticket.status != TICKET_ISSUED or ticket.order.status != ORDER_PAID:
        raise _error(409, "TICKET_NOT_VALID", "Ticket cannot generate a QR credential")
    qr_data, expires_at = create_ticket_qr(
        ticket_id=ticket.id,
        ticket_version=ticket.version,
        slot_id=ticket.slot_id,
        settings=settings,
    )
    return TicketQrResponse(
        ticket_id=str(ticket.id),
        ticket_code=ticket.ticket_code,
        qr_data=qr_data,
        expires_at=_aware(expires_at),
        is_demo=True,
    )


def _validation_response(
    validation: TicketValidation,
    ticket: ElectronicTicket,
) -> GateValidationResponse:
    return GateValidationResponse(
        validation_id=str(validation.id),
        ticket_id=str(ticket.id),
        ticket_code=ticket.ticket_code,
        result=validation.result,
        # 闸机记录从 SQLite 读回时也可能成为 naive datetime, 响应必须保持明确 UTC.
        validated_at=_aware(validation.validated_at),
        gate_code=validation.gate_code,
        is_demo=True,
    )


async def validate_ticket_at_gate(
    session: AsyncSession,
    *,
    qr_data: str,
    request_id: str,
    gate_code: str,
    validator: User,
    settings: Settings,
) -> GateValidationResponse:
    request_hash = _hash_payload(
        {
            "gate_code": gate_code,
            "qr_digest": sha256(qr_data.encode()).hexdigest(),
        }
    )
    existing = await session.scalar(
        select(TicketValidation).where(TicketValidation.request_id == request_id)
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Validation request payload differs")
        ticket = await session.get(ElectronicTicket, existing.ticket_id)
        assert ticket is not None
        return _validation_response(existing, ticket)

    try:
        claims = decode_token(qr_data, expected_type="ticket_qr", settings=settings)
        ticket_id = UUID(str(claims["sub"]))
        claimed_slot_id = UUID(str(claims["sid"]))
        claimed_version = int(claims["ver"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise _error(400, "INVALID_QR", "QR credential is invalid or expired") from exc

    ticket = await session.scalar(
        select(ElectronicTicket)
        .options(
            joinedload(ElectronicTicket.order),
            joinedload(ElectronicTicket.slot),
        )
        .where(ElectronicTicket.id == ticket_id)
    )
    if ticket is None:
        raise _error(404, "TICKET_NOT_FOUND", "Electronic ticket not found")
    if (
        ticket.order.status != ORDER_PAID
        or ticket.slot_id != claimed_slot_id
        or ticket.version != claimed_version
    ):
        raise _error(409, "TICKET_NOT_VALID", "Ticket or QR version is no longer valid")

    scenic_now = datetime.now(SCENIC_TIMEZONE)
    validation_starts = datetime.combine(
        ticket.slot.visit_date,
        ticket.slot.start_time,
        tzinfo=SCENIC_TIMEZONE,
    )
    validation_ends = datetime.combine(
        ticket.slot.visit_date,
        ticket.slot.end_time,
        tzinfo=SCENIC_TIMEZONE,
    )
    if not validation_starts <= scenic_now <= validation_ends:
        raise _error(
            409,
            "TICKET_OUTSIDE_VALIDATION_WINDOW",
            "Ticket is not valid at the current scenic-area time",
        )

    now = datetime.now(UTC)
    consumed = await session.execute(
        update(ElectronicTicket)
        .execution_options(synchronize_session=False)
        .where(
            ElectronicTicket.id == ticket.id,
            ElectronicTicket.status == TICKET_ISSUED,
            ElectronicTicket.version == claimed_version,
        )
        .values(
            status=TICKET_USED,
            used_at=now,
            version=ElectronicTicket.version + 1,
        )
    )
    if consumed.rowcount != 1:
        await session.rollback()
        concurrent = await session.scalar(
            select(TicketValidation).where(TicketValidation.request_id == request_id)
        )
        if concurrent is not None and concurrent.request_hash == request_hash:
            current_ticket = await session.get(ElectronicTicket, concurrent.ticket_id)
            assert current_ticket is not None
            return _validation_response(concurrent, current_ticket)
        raise _error(409, "TICKET_ALREADY_USED", "Ticket has already been used or voided")

    validation = TicketValidation(
        ticket_id=ticket.id,
        validator_user_id=validator.id,
        request_id=request_id,
        request_hash=request_hash,
        gate_code=gate_code,
        result="ACCEPTED",
        validated_at=now,
    )
    session.add(validation)
    await session.commit()
    await session.refresh(validation)
    refreshed_ticket = await session.get(ElectronicTicket, ticket.id)
    assert refreshed_ticket is not None
    return _validation_response(validation, refreshed_ticket)


async def verify_ticket_face_demo(
    session: AsyncSession,
    *,
    ticket_id: UUID,
    user: User,
    sample: FaceDemoSample,
    provider: FaceGateProvider | None = None,
) -> FaceDemoVerifyResponse:
    """演示可替换的人脸 Provider, 但不处理生物信息也不执行票据核销。"""

    ticket = await session.scalar(
        select(ElectronicTicket)
        .options(joinedload(ElectronicTicket.order))
        .where(ElectronicTicket.id == ticket_id)
    )
    # 所有权失败返回同一个 404, 防止游客通过接口枚举他人的电子票。
    if ticket is None or ticket.user_id != user.id:
        raise _error(404, "TICKET_NOT_FOUND", "Electronic ticket not found")
    if ticket.order.status != ORDER_PAID or ticket.status != TICKET_ISSUED:
        raise _error(
            409,
            "FACE_DEMO_TICKET_NOT_ELIGIBLE",
            "Only a paid and issued ticket can use the face-gate demo",
        )

    verification = await (provider or DemoFaceGateProvider()).verify(
        expected_subject_id=str(ticket.user_id),
        sample=sample,
    )
    # face-demo 是展示 Provider seam 的只读端点。即使未来误注入真实适配器,
    # 也必须拒绝任何生物处理或放行声明, 真实核销只能走管理员 gate 事务。
    if (
        not verification.is_demo
        or verification.biometric_processed
        or verification.admission_granted
    ):
        raise RuntimeError("Face demo provider violated the no-biometric safety boundary")

    return FaceDemoVerifyResponse(
        ticket_id=str(ticket.id),
        ticket_code=ticket.ticket_code,
        result=verification.result,
        provider=verification.provider,
        is_demo=True,
        biometric_processed=False,
        admission_granted=False,
        disclaimer=(
            "仅为无生物信息的人脸接入演示; 未调用摄像头或活体检测, "
            "不会放行或核销门票。"
        ),
    )

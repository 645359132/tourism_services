"""Server-authoritative shop catalog, cart, checkout, and demo payment flows."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models.commerce import (
    Campaign,
    Cart,
    CartItem,
    DeliveryAddress,
    Product,
    ProductInventory,
    ShopCategory,
    ShopOrder,
    ShopOrderItem,
)
from app.db.models.user import User
from app.providers.payment import DemoPaymentProvider
from app.schemas.commerce import (
    CampaignResponse,
    CartItemResponse,
    CartResponse,
    CategoryResponse,
    DeliveryRequest,
    ProductResponse,
    ShopOrderItemResponse,
    ShopOrderResponse,
)
from app.services.points import award_points


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


def _cart_statement():
    return (
        select(Cart)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Cart.items).joinedload(CartItem.product).joinedload(Product.inventory)
        )
    )


def _order_statement():
    return (
        select(ShopOrder)
        .execution_options(populate_existing=True)
        .options(
            selectinload(ShopOrder.items),
            joinedload(ShopOrder.delivery_address),
        )
    )


async def _active_campaign(
    session: AsyncSession,
    product: Product,
    *,
    now: datetime | None = None,
) -> Campaign | None:
    moment = now or datetime.now(UTC)
    campaigns = list(
        await session.scalars(
            select(Campaign).where(
                Campaign.is_active.is_(True),
                or_(
                    Campaign.product_id == product.id,
                    Campaign.category_id == product.category_id,
                ),
            )
        )
    )
    applicable = [
        campaign
        for campaign in campaigns
        if _aware(campaign.starts_at) <= moment < _aware(campaign.ends_at)
    ]
    return max(applicable, key=lambda item: item.discount_bps, default=None)


async def authoritative_price(
    session: AsyncSession,
    product: Product,
) -> tuple[int, Campaign | None]:
    campaign = await _active_campaign(session, product)
    if campaign is None:
        return product.price_cents, None
    effective = product.price_cents * (10_000 - campaign.discount_bps) // 10_000
    return max(effective, 0), campaign


async def product_response(
    session: AsyncSession,
    product: Product,
) -> ProductResponse:
    effective, campaign = await authoritative_price(session, product)
    return ProductResponse(
        id=str(product.id),
        category_id=str(product.category_id),
        sku=product.sku,
        name=product.name,
        description=product.description,
        price_cents=product.price_cents,
        effective_price_cents=effective,
        stock=product.inventory.stock,
        points_price=product.points_price,
        tags=product.tags,
        campaign_id=None if campaign is None else str(campaign.id),
        campaign_name=None if campaign is None else campaign.name,
        provider="demo_catalog",
        is_demo=product.is_demo,
    )


async def list_categories(session: AsyncSession) -> list[CategoryResponse]:
    categories = list(
        await session.scalars(
            select(ShopCategory)
            .where(ShopCategory.is_active.is_(True))
            .order_by(ShopCategory.sort_order, ShopCategory.code)
        )
    )
    return [
        CategoryResponse(
            id=str(category.id),
            code=category.code,
            name=category.name,
            description=category.description,
            sort_order=category.sort_order,
        )
        for category in categories
    ]


async def list_products(
    session: AsyncSession,
    *,
    category_id: UUID | None = None,
) -> list[ProductResponse]:
    await expire_shop_orders(session)
    await session.commit()
    statement = (
        select(Product)
        .options(joinedload(Product.inventory))
        .where(Product.is_active.is_(True))
        .order_by(Product.sku)
    )
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    products = list(await session.scalars(statement))
    return [await product_response(session, product) for product in products]


async def list_campaigns(session: AsyncSession) -> list[CampaignResponse]:
    now = datetime.now(UTC)
    campaigns = list(await session.scalars(select(Campaign).order_by(Campaign.code)))
    return [
        CampaignResponse(
            id=str(campaign.id),
            code=campaign.code,
            name=campaign.name,
            description=campaign.description,
            product_id=None if campaign.product_id is None else str(campaign.product_id),
            category_id=None if campaign.category_id is None else str(campaign.category_id),
            discount_bps=campaign.discount_bps,
            starts_at=_aware(campaign.starts_at),
            ends_at=_aware(campaign.ends_at),
            kind="DISCOUNT",
            active=(
                campaign.is_active and _aware(campaign.starts_at) <= now < _aware(campaign.ends_at)
            ),
            provider="demo_campaign",
            is_demo=True,
        )
        for campaign in campaigns
    ]


async def _load_cart(session: AsyncSession, user_id: UUID) -> Cart | None:
    return await session.scalar(_cart_statement().where(Cart.user_id == user_id))


async def _ensure_cart(session: AsyncSession, user_id: UUID) -> Cart:
    cart = await _load_cart(session, user_id)
    if cart is not None:
        return cart

    bind = session.get_bind()
    values = {"id": uuid4(), "user_id": user_id, "version": 1}
    if bind.dialect.name == "sqlite":
        # End the read transaction before requesting SQLite's single writer
        # lock, then release it before the caller performs follow-up work.
        # This path is reached only for a genuinely missing cart, and the
        # conflict-safe insert makes the early commit idempotent.
        await session.rollback()
        await session.execute(sqlite_insert(Cart).values(**values).on_conflict_do_nothing())
        await session.commit()
    elif bind.dialect.name == "postgresql":
        await session.execute(
            postgresql_insert(Cart)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[Cart.user_id])
        )
    elif await session.scalar(select(Cart).where(Cart.user_id == user_id)) is None:
        session.add(Cart(**values))
        await session.flush()
    cart = await _load_cart(session, user_id)
    assert cart is not None
    return cart


async def cart_response(session: AsyncSession, cart: Cart) -> CartResponse:
    items: list[CartItemResponse] = []
    subtotal = 0
    total = 0
    for item in sorted(cart.items, key=lambda value: value.product.sku):
        effective, campaign = await authoritative_price(session, item.product)
        base_line = item.product.price_cents * item.quantity
        effective_line = effective * item.quantity
        subtotal += base_line
        total += effective_line
        items.append(
            CartItemResponse(
                id=str(item.id),
                product_id=str(item.product.id),
                sku=item.product.sku,
                product_name=item.product.name,
                quantity=item.quantity,
                unit_price_cents=effective,
                subtotal_cents=effective_line,
                stock=item.product.inventory.stock,
                campaign_id=None if campaign is None else str(campaign.id),
                campaign_name=None if campaign is None else campaign.name,
            )
        )
    return CartResponse(
        id=str(cart.id),
        items=items,
        total_quantity=sum(item.quantity for item in cart.items),
        subtotal_cents=subtotal,
        discount_cents=subtotal - total,
        total_cents=total,
        updated_at=_aware(cart.updated_at),
    )


async def get_cart(session: AsyncSession, *, user: User) -> Cart:
    await expire_shop_orders(session)
    await session.commit()
    return await _ensure_cart(session, user.id)


async def get_existing_cart(session: AsyncSession, *, user: User) -> Cart | None:
    """Load a cart without expiration writes or create-on-read behavior."""

    return await _load_cart(session, user.id)


async def add_cart_item(
    session: AsyncSession,
    *,
    user: User,
    product_id: UUID,
    quantity: int,
) -> Cart:
    await expire_shop_orders(session)
    await session.commit()
    cart = await _ensure_cart(session, user.id)
    product = await session.scalar(
        select(Product)
        .options(joinedload(Product.inventory))
        .where(Product.id == product_id, Product.is_active.is_(True))
    )
    if product is None:
        raise _error(404, "PRODUCT_NOT_FOUND", "Product not found")
    existing = next((item for item in cart.items if item.product_id == product_id), None)
    next_quantity = quantity if existing is None else existing.quantity + quantity
    if next_quantity > 99:
        raise _error(422, "CART_QUANTITY_LIMIT", "Cart quantity exceeds 99")
    if next_quantity > product.inventory.stock:
        raise _error(409, "INSUFFICIENT_STOCK", "Requested quantity exceeds current stock")
    effective, _ = await authoritative_price(session, product)
    if existing is None:
        session.add(
            CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=next_quantity,
                added_price_cents=effective,
            )
        )
    else:
        existing.quantity = next_quantity
        existing.added_price_cents = effective
    cart.version += 1
    await session.commit()
    loaded = await session.scalar(_cart_statement().where(Cart.id == cart.id))
    assert loaded is not None
    return loaded


async def update_cart_item(
    session: AsyncSession,
    *,
    user: User,
    item_id: UUID,
    quantity: int,
) -> Cart:
    await expire_shop_orders(session)
    await session.commit()
    cart = await _ensure_cart(session, user.id)
    item = next((candidate for candidate in cart.items if candidate.id == item_id), None)
    if item is None:
        raise _error(404, "CART_ITEM_NOT_FOUND", "Cart item not found")
    if quantity > item.product.inventory.stock:
        raise _error(409, "INSUFFICIENT_STOCK", "Requested quantity exceeds current stock")
    item.quantity = quantity
    item.added_price_cents, _ = await authoritative_price(session, item.product)
    cart.version += 1
    await session.commit()
    loaded = await session.scalar(_cart_statement().where(Cart.id == cart.id))
    assert loaded is not None
    return loaded


async def remove_cart_item(
    session: AsyncSession,
    *,
    user: User,
    item_id: UUID,
) -> Cart:
    cart = await _ensure_cart(session, user.id)
    item = next((candidate for candidate in cart.items if candidate.id == item_id), None)
    if item is None:
        raise _error(404, "CART_ITEM_NOT_FOUND", "Cart item not found")
    await session.delete(item)
    cart.version += 1
    await session.commit()
    loaded = await session.scalar(_cart_statement().where(Cart.id == cart.id))
    assert loaded is not None
    return loaded


async def _load_order(session: AsyncSession, order_id: UUID) -> ShopOrder | None:
    return await session.scalar(_order_statement().where(ShopOrder.id == order_id))


async def expire_shop_orders(session: AsyncSession) -> int:
    now = datetime.now(UTC)
    orders = list(
        await session.scalars(
            _order_statement().where(
                ShopOrder.status == "PENDING_PAYMENT",
                ShopOrder.expires_at <= now,
            )
        )
    )
    expired = 0
    for order in orders:
        transitioned = await session.execute(
            update(ShopOrder)
            .execution_options(synchronize_session=False)
            .where(
                ShopOrder.id == order.id,
                ShopOrder.status == "PENDING_PAYMENT",
                ShopOrder.version == order.version,
                ShopOrder.expires_at <= now,
            )
            .values(
                status="EXPIRED",
                version=ShopOrder.version + 1,
            )
        )
        if transitioned.rowcount != 1:
            continue
        for item in sorted(order.items, key=lambda value: str(value.product_id)):
            restored = await session.execute(
                update(ProductInventory)
                .execution_options(synchronize_session=False)
                .where(ProductInventory.product_id == item.product_id)
                .values(
                    stock=ProductInventory.stock + item.quantity,
                    version=ProductInventory.version + 1,
                )
            )
            if restored.rowcount != 1:
                raise RuntimeError("Expired shop order inventory ledger is inconsistent")
        expired += 1
    return expired


async def _owned_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    actor_id: UUID,
    actor_is_admin: bool,
) -> ShopOrder:
    order = await _load_order(session, order_id)
    if order is None or (order.user_id != actor_id and not actor_is_admin):
        raise _error(404, "SHOP_ORDER_NOT_FOUND", "Shop order not found")
    return order


def order_response(order: ShopOrder) -> ShopOrderResponse:
    delivery = order.delivery_address
    return ShopOrderResponse(
        id=str(order.id),
        order_no=order.order_no,
        status=order.status,
        total_cents=order.total_cents,
        total_quantity=order.total_quantity,
        subtotal_cents=order.subtotal_cents,
        discount_cents=order.discount_cents,
        points_awarded=order.points_awarded,
        items=[
            ShopOrderItemResponse(
                id=str(item.id),
                product_id=str(item.product_id),
                sku=item.sku,
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                subtotal_cents=item.line_total_cents,
                campaign_id=None if item.campaign_id is None else str(item.campaign_id),
            )
            for item in order.items
        ],
        delivery_name=delivery.recipient,
        delivery_phone=delivery.phone,
        delivery_address=(f"{delivery.province}{delivery.city}{delivery.address_line}"),
        provider="demo_payment",
        is_demo=True,
        created_at=_aware(order.created_at),
        paid_at=None if order.paid_at is None else _aware(order.paid_at),
    )


async def checkout_cart(
    session: AsyncSession,
    *,
    user: User,
    delivery: DeliveryRequest,
    idempotency_key: str,
    settings: Settings,
) -> ShopOrder:
    actor_id = user.id
    await expire_shop_orders(session)
    await session.commit()
    request_hash = _hash_payload({"delivery": delivery.model_dump(mode="json")})
    existing = await session.scalar(
        _order_statement().where(
            ShopOrder.user_id == actor_id,
            ShopOrder.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Checkout key payload differs")
        return existing

    cart = await _load_cart(session, actor_id)
    if cart is None:
        await session.rollback()
        raise _error(409, "CART_EMPTY", "Cart is empty")
    locked = await session.execute(
        update(Cart)
        .execution_options(synchronize_session=False)
        .where(Cart.id == cart.id)
        .values(version=Cart.version + 1)
    )
    if locked.rowcount != 1:
        await session.rollback()
        raise _error(409, "CART_CONFLICT", "Cart changed during checkout")
    existing = await session.scalar(
        _order_statement().where(
            ShopOrder.user_id == actor_id,
            ShopOrder.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            await session.rollback()
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Checkout key payload differs")
        order_id = existing.id
        await session.rollback()
        replayed = await _load_order(session, order_id)
        assert replayed is not None
        return replayed
    cart = await session.scalar(_cart_statement().where(Cart.id == cart.id))
    assert cart is not None
    if not cart.items:
        await session.rollback()
        raise _error(409, "CART_EMPTY", "Cart is empty")

    priced_items: list[tuple[CartItem, int, Campaign | None]] = []
    for item in cart.items:
        if not item.product.is_active:
            await session.rollback()
            raise _error(409, "PRODUCT_UNAVAILABLE", "A cart product is unavailable")
        effective, campaign = await authoritative_price(session, item.product)
        priced_items.append((item, effective, campaign))

    for item, _, _ in sorted(priced_items, key=lambda value: str(value[0].product_id)):
        product_name = item.product.name
        reserved = await session.execute(
            update(ProductInventory)
            .execution_options(synchronize_session=False)
            .where(
                ProductInventory.product_id == item.product_id,
                ProductInventory.stock >= item.quantity,
            )
            .values(
                stock=ProductInventory.stock - item.quantity,
                version=ProductInventory.version + 1,
            )
        )
        if reserved.rowcount != 1:
            await session.rollback()
            raise _error(
                409,
                "INSUFFICIENT_STOCK",
                f"{product_name} has insufficient stock",
            )

    address = DeliveryAddress(
        user_id=actor_id,
        recipient=delivery.name,
        phone=delivery.phone,
        province=delivery.province,
        city=delivery.city,
        address_line=delivery.address_line,
        postal_code=delivery.postal_code,
    )
    session.add(address)
    await session.flush()
    subtotal = sum(item.product.price_cents * item.quantity for item, _, _ in priced_items)
    total = sum(effective * item.quantity for item, effective, _ in priced_items)
    total_quantity = sum(item.quantity for item, _, _ in priced_items)
    order_id = uuid4()
    order = ShopOrder(
        id=order_id,
        order_no=f"SO-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}",
        user_id=actor_id,
        delivery_address_id=address.id,
        status="PENDING_PAYMENT",
        total_cents=total,
        subtotal_cents=subtotal,
        discount_cents=subtotal - total,
        total_quantity=total_quantity,
        points_awarded=0,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.shop_order_reservation_minutes),
    )
    order.items.extend(
        ShopOrderItem(
            product_id=item.product_id,
            campaign_id=None if campaign is None else campaign.id,
            sku=item.product.sku,
            product_name=item.product.name,
            quantity=item.quantity,
            unit_price_cents=effective,
            line_total_cents=effective * item.quantity,
        )
        for item, effective, campaign in priced_items
    )
    session.add(order)
    await session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.user_id == actor_id,
                ShopOrder.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(409, "CHECKOUT_CONFLICT", "Checkout could not be completed") from exc
        order_id = concurrent.id
    loaded = await _load_order(session, order_id)
    assert loaded is not None
    return loaded


async def pay_shop_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
    idempotency_key: str,
    payment_provider: DemoPaymentProvider | None = None,
) -> ShopOrder:
    actor_id = user.id
    actor_is_admin = "admin" in user.role_names
    order = await _owned_order(
        session,
        order_id=order_id,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
    )
    if order.status == "PAID":
        if order.payment_idempotency_key != idempotency_key:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Payment key differs")
        return order
    if order.status != "PENDING_PAYMENT":
        raise _error(409, "SHOP_ORDER_NOT_PAYABLE", "Shop order is not payable")
    now = datetime.now(UTC)
    if _aware(order.expires_at) <= now:
        await expire_shop_orders(session)
        await session.commit()
        raise _error(409, "SHOP_ORDER_EXPIRED", "Shop order hold has expired")
    provider = payment_provider or DemoPaymentProvider()
    payment = await provider.authorize(
        order_no=order.order_no,
        amount_cents=order.total_cents,
        idempotency_key=idempotency_key,
    )
    points = max(order.total_cents // 100, 1)
    transitioned = await session.execute(
        update(ShopOrder)
        .execution_options(synchronize_session=False)
        .where(
            ShopOrder.id == order.id,
            ShopOrder.status == "PENDING_PAYMENT",
            ShopOrder.version == order.version,
            ShopOrder.expires_at > now,
        )
        .values(
            status="PAID",
            payment_idempotency_key=idempotency_key,
            payment_reference=payment.reference,
            paid_at=now,
            points_awarded=points,
            version=ShopOrder.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        concurrent = await _owned_order(
            session,
            order_id=order_id,
            actor_id=actor_id,
            actor_is_admin=actor_is_admin,
        )
        if concurrent.status == "PAID" and concurrent.payment_idempotency_key == idempotency_key:
            return concurrent
        raise _error(409, "SHOP_ORDER_NOT_PAYABLE", "Shop order is not payable")
    await award_points(
        session,
        user_id=order.user_id,
        points=points,
        source_type="SHOP_ORDER",
        source_id=order.id,
        description=f"商城订单 {order.order_no} 支付积分",
    )
    await session.commit()
    loaded = await _load_order(session, order.id)
    assert loaded is not None
    return loaded


async def list_shop_orders(
    session: AsyncSession,
    *,
    user: User,
    offset: int,
    limit: int,
) -> tuple[list[ShopOrder], int]:
    await expire_shop_orders(session)
    await session.commit()
    statement = _order_statement().order_by(
        ShopOrder.created_at.desc(),
        ShopOrder.id.desc(),
    )
    if "admin" not in user.role_names:
        statement = statement.where(ShopOrder.user_id == user.id)
    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    return list(await session.scalars(statement.offset(offset).limit(limit))), total


async def get_shop_order(
    session: AsyncSession,
    *,
    order_id: UUID,
    user: User,
) -> ShopOrder:
    await expire_shop_orders(session)
    await session.commit()
    return await _owned_order(
        session,
        order_id=order_id,
        actor_id=user.id,
        actor_is_admin="admin" in user.role_names,
    )

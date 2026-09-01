"""Public shop catalog and authenticated cart, orders, points, and sharing APIs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_tourist
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.commerce import (
    AddCartItemRequest,
    CampaignListResponse,
    CartResponse,
    CategoryListResponse,
    CheckoutRequest,
    PayShopOrderRequest,
    PointAccountResponse,
    PointLedgerListResponse,
    ProductListResponse,
    RedeemRequest,
    RedemptionResponse,
    RewardListResponse,
    ShareRequest,
    ShareResponse,
    ShopOrderListResponse,
    ShopOrderResponse,
    UpdateCartItemRequest,
)
from app.services.commerce import (
    add_cart_item,
    cart_response,
    checkout_cart,
    get_cart,
    get_shop_order,
    list_campaigns,
    list_categories,
    list_products,
    list_shop_orders,
    order_response,
    pay_shop_order,
    remove_cart_item,
    update_cart_item,
)
from app.services.points import (
    list_point_ledger,
    list_rewards,
    point_account_response,
    redeem_reward,
    redemption_response,
    share_response,
    verify_share,
)

router = APIRouter(tags=["commerce"])


@router.get("/shop/categories", response_model=CategoryListResponse)
async def shop_categories(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CategoryListResponse:
    return CategoryListResponse(items=await list_categories(session))


@router.get("/shop/products", response_model=ProductListResponse)
async def shop_products(
    session: Annotated[AsyncSession, Depends(get_session)],
    category_id: Annotated[UUID | None, Query()] = None,
) -> ProductListResponse:
    return ProductListResponse(items=await list_products(session, category_id=category_id))


@router.get("/shop/campaigns", response_model=CampaignListResponse)
async def shop_campaigns(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CampaignListResponse:
    return CampaignListResponse(items=await list_campaigns(session))


@router.get("/shop/cart", response_model=CartResponse)
async def shop_cart(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CartResponse:
    cart = await get_cart(session, user=current_user)
    response = await cart_response(session, cart)
    await session.commit()
    return response


@router.post("/shop/cart/items", response_model=CartResponse)
async def add_shop_cart_item(
    payload: AddCartItemRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CartResponse:
    cart = await add_cart_item(
        session,
        user=current_user,
        product_id=payload.product_id,
        quantity=payload.quantity,
    )
    return await cart_response(session, cart)


@router.patch("/shop/cart/items/{item_id}", response_model=CartResponse)
@router.put("/shop/cart/items/{item_id}", response_model=CartResponse)
async def patch_shop_cart_item(
    item_id: UUID,
    payload: UpdateCartItemRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CartResponse:
    cart = await update_cart_item(
        session,
        user=current_user,
        item_id=item_id,
        quantity=payload.quantity,
    )
    return await cart_response(session, cart)


@router.delete("/shop/cart/items/{item_id}", response_model=CartResponse)
async def delete_shop_cart_item(
    item_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CartResponse:
    cart = await remove_cart_item(session, user=current_user, item_id=item_id)
    return await cart_response(session, cart)


@router.post(
    "/shop/cart/checkout",
    response_model=ShopOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def checkout_shop_cart(
    payload: CheckoutRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShopOrderResponse:
    order = await checkout_cart(
        session,
        user=current_user,
        delivery=payload.delivery,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return order_response(order)


@router.get("/shop/orders", response_model=ShopOrderListResponse)
async def shop_orders(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShopOrderListResponse:
    orders = await list_shop_orders(session, user=current_user)
    return ShopOrderListResponse(items=[order_response(order) for order in orders])


@router.get("/shop/orders/{order_id}", response_model=ShopOrderResponse)
async def shop_order_detail(
    order_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShopOrderResponse:
    return order_response(await get_shop_order(session, order_id=order_id, user=current_user))


@router.post("/shop/orders/{order_id}/pay", response_model=ShopOrderResponse)
async def pay_order(
    order_id: UUID,
    payload: PayShopOrderRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShopOrderResponse:
    return order_response(
        await pay_shop_order(
            session,
            order_id=order_id,
            user=current_user,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.get("/points/account", response_model=PointAccountResponse)
async def points_account(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PointAccountResponse:
    response = await point_account_response(session, user_id=current_user.id)
    await session.commit()
    return response


@router.get("/points/ledger", response_model=PointLedgerListResponse)
async def points_ledger(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PointLedgerListResponse:
    return PointLedgerListResponse(items=await list_point_ledger(session, user_id=current_user.id))


@router.get("/points/rewards", response_model=RewardListResponse)
async def point_rewards(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RewardListResponse:
    return RewardListResponse(items=await list_rewards(session))


@router.post("/points/redeem", response_model=RedemptionResponse)
async def redeem_points(
    payload: RedeemRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedemptionResponse:
    redemption = await redeem_reward(
        session,
        user=current_user,
        reward_id=payload.reward_id,
        quantity=payload.quantity,
        idempotency_key=payload.idempotency_key,
    )
    return redemption_response(redemption)


@router.post("/shares", response_model=ShareResponse)
async def create_share(
    payload: ShareRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShareResponse:
    share = await verify_share(
        session,
        user=current_user,
        content_type=payload.content_type,
        ref_id=payload.ref_id,
        platform=payload.platform,
        caption=payload.caption,
        idempotency_key=payload.idempotency_key,
    )
    return share_response(share)

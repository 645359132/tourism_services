"""Shop, cart, orders, points, rewards, redemptions, and sharing contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import PaginatedResponse


class CategoryResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    sort_order: int


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]


class ProductResponse(BaseModel):
    id: str
    category_id: str
    sku: str
    name: str
    description: str
    price_cents: int
    effective_price_cents: int
    stock: int
    points_price: int | None
    tags: list[str]
    campaign_id: str | None
    campaign_name: str | None
    provider: str = "demo_catalog"
    is_demo: bool = True


class ProductListResponse(BaseModel):
    items: list[ProductResponse]


class CampaignResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    product_id: str | None
    category_id: str | None
    discount_bps: int
    starts_at: datetime
    ends_at: datetime
    kind: Literal["DISCOUNT"] = "DISCOUNT"
    active: bool
    provider: str = "demo_campaign"
    is_demo: bool = True


class CampaignListResponse(BaseModel):
    items: list[CampaignResponse]


class CartItemResponse(BaseModel):
    id: str
    product_id: str
    sku: str
    product_name: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int
    stock: int
    campaign_id: str | None
    campaign_name: str | None


class CartResponse(BaseModel):
    id: str
    items: list[CartItemResponse]
    total_quantity: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    updated_at: datetime


class AddCartItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: int = Field(ge=1, le=99)


class UpdateCartItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1, le=99)


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=6, max_length=32)
    province: str = Field(min_length=1, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    address_line: str = Field(min_length=3, max_length=300)
    postal_code: str | None = Field(default=None, max_length=20)

    @field_validator("name", "phone", "province", "city", "address_line", "postal_code")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: DeliveryRequest
    idempotency_key: str = Field(min_length=8, max_length=128)


class PayShopOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class ShopOrderItemResponse(BaseModel):
    id: str
    product_id: str
    sku: str
    product_name: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int
    campaign_id: str | None


class ShopOrderResponse(BaseModel):
    id: str
    order_no: str
    status: Literal["PENDING_PAYMENT", "PAID", "CANCELLED", "EXPIRED"]
    total_cents: int
    total_quantity: int
    subtotal_cents: int
    discount_cents: int
    points_awarded: int
    items: list[ShopOrderItemResponse]
    delivery_name: str
    delivery_phone: str
    delivery_address: str
    provider: str = "demo_payment"
    is_demo: bool = True
    created_at: datetime
    paid_at: datetime | None


class ShopOrderListResponse(PaginatedResponse):
    items: list[ShopOrderResponse]


class PointAccountResponse(BaseModel):
    balance: int
    lifetime_earned: int
    lifetime_spent: int
    updated_at: datetime


class PointLedgerResponse(BaseModel):
    id: str
    kind: Literal["EARN", "SPEND", "REFUND"]
    amount: int
    balance_after: int
    reason: str
    reference_type: str
    reference_id: str
    created_at: datetime


class PointLedgerListResponse(PaginatedResponse):
    items: list[PointLedgerResponse]


class RewardResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    points_cost: int
    stock: int
    provider: str = "demo_rewards"
    is_demo: bool = True


class RewardListResponse(BaseModel):
    items: list[RewardResponse]


class RedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reward_id: UUID
    quantity: int = Field(default=1, ge=1, le=20)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RedemptionResponse(BaseModel):
    id: str
    redemption_no: str
    reward_id: str
    reward_name: str
    quantity: int
    points_spent: int
    status: Literal["CONFIRMED", "CANCELLED"]
    provider: str = "demo_rewards"
    is_demo: bool = True
    created_at: datetime


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["PRODUCT"]
    ref_id: str = Field(min_length=1, max_length=128)
    platform: Literal["demo_moments", "demo_group"]
    caption: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ShareResponse(BaseModel):
    id: str
    content_type: str
    ref_id: str
    platform: str
    caption: str
    verified: bool
    points_awarded: int
    provider: str = "demo_share_verifier"
    is_demo: bool = True
    created_at: datetime

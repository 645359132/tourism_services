"""Public ticketing request and response contracts."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


class TicketTypeItem(BaseModel):
    id: str
    code: str
    name: str
    audience: str
    description: str
    base_price_cents: int


class TicketTypeListResponse(BaseModel):
    items: list[TicketTypeItem]


class TicketSlotItem(BaseModel):
    id: str
    ticket_type_id: str
    visit_date: date
    start_time: time
    end_time: time
    capacity: int
    remaining: int
    unit_price_cents: int
    pricing_explanation: list[str]


class TicketSlotListResponse(BaseModel):
    items: list[TicketSlotItem]


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: UUID
    quantity: int = Field(ge=1, le=20)


class QuoteResponse(BaseModel):
    id: str
    slot_id: str
    ticket_type_id: str
    visit_date: date
    start_time: time
    end_time: time
    quantity: int
    unit_price_cents: int
    total_cents: int
    expires_at: datetime
    quote_token: str
    pricing_explanation: list[str]


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: UUID
    quantity: int = Field(ge=1, le=20)
    quote_token: str = Field(min_length=32, max_length=4096)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PayOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class CancelOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=8, max_length=128)


class RefundOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RescheduleOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_slot_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=128)


class TicketSummary(BaseModel):
    id: str
    ticket_code: str
    status: str


class TicketOrderResponse(BaseModel):
    id: str
    order_no: str
    status: str
    ticket_type_name: str
    slot_id: str
    visit_date: date
    start_time: time
    end_time: time
    quantity: int
    unit_price_cents: int
    total_cents: int
    expires_at: datetime
    refund_cutoff_hours: int
    refund_deadline_at: datetime | None
    refundable: bool
    tickets: list[TicketSummary]


class TicketOrderListResponse(PaginatedResponse):
    items: list[TicketOrderResponse]


class TicketQrResponse(BaseModel):
    ticket_id: str
    ticket_code: str
    qr_data: str
    expires_at: datetime
    is_demo: bool = True


class GateValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qr_data: str = Field(min_length=1, max_length=4096)
    request_id: str = Field(min_length=8, max_length=128)
    gate_code: str = Field(min_length=1, max_length=64)


class GateValidationResponse(BaseModel):
    validation_id: str
    ticket_id: str
    ticket_code: str
    result: str
    validated_at: datetime
    gate_code: str
    is_demo: bool = True


class FaceDemoVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample: Literal["OWNER", "OTHER"]
    # Literal[True] 让“明确同意”成为接口校验的一部分, false 或漏传都会在进入业务层前失败。
    consent: Literal[True]


class FaceDemoVerifyResponse(BaseModel):
    ticket_id: str
    ticket_code: str
    result: Literal["DEMO_MATCHED", "DEMO_NOT_MATCHED"]
    provider: str = "demo_face_gate"
    is_demo: bool = True
    biometric_processed: bool = False
    admission_granted: bool = False
    disclaimer: str

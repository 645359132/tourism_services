"""Versioned ticket catalog, order, after-sale, QR, and gate endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_admin, require_tourist
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.ticketing import (
    CreateOrderRequest,
    GateValidationRequest,
    GateValidationResponse,
    PayOrderRequest,
    QuoteRequest,
    QuoteResponse,
    RefundOrderRequest,
    RescheduleOrderRequest,
    TicketOrderListResponse,
    TicketOrderResponse,
    TicketQrResponse,
    TicketSlotListResponse,
    TicketTypeListResponse,
)
from app.services.ticketing import (
    create_ticket_order,
    create_ticket_qr_response,
    get_ticket_order,
    list_ticket_orders,
    list_ticket_slots,
    list_ticket_types,
    order_response,
    pay_ticket_order,
    quote_ticket_order,
    refund_ticket_order,
    reschedule_ticket_order,
    validate_ticket_at_gate,
)

router = APIRouter(prefix="/ticketing", tags=["ticketing"])


@router.get("/types", response_model=TicketTypeListResponse)
async def ticket_types(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketTypeListResponse:
    return TicketTypeListResponse(items=await list_ticket_types(session))


@router.get("/slots", response_model=TicketSlotListResponse)
async def ticket_slots(
    session: Annotated[AsyncSession, Depends(get_session)],
    visit_date: Annotated[date, Query()],
    ticket_type_id: Annotated[UUID | None, Query()] = None,
) -> TicketSlotListResponse:
    items = await list_ticket_slots(
        session,
        visit_date=visit_date,
        ticket_type_id=ticket_type_id,
    )
    return TicketSlotListResponse(items=items)


@router.post("/quotes", response_model=QuoteResponse)
async def quote(
    payload: QuoteRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QuoteResponse:
    return await quote_ticket_order(
        session,
        slot_id=payload.slot_id,
        quantity=payload.quantity,
        settings=request.app.state.settings,
    )


@router.post(
    "/orders",
    response_model=TicketOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    payload: CreateOrderRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> TicketOrderResponse:
    order = await create_ticket_order(
        session,
        user=current_user,
        slot_id=payload.slot_id,
        quantity=payload.quantity,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return order_response(order)


@router.get("/orders", response_model=TicketOrderListResponse)
async def orders(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketOrderListResponse:
    found = await list_ticket_orders(session, user=current_user)
    return TicketOrderListResponse(items=[order_response(order) for order in found])


@router.get("/orders/{order_id}", response_model=TicketOrderResponse)
async def order_detail(
    order_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketOrderResponse:
    order = await get_ticket_order(session, order_id=order_id, user=current_user)
    return order_response(order)


@router.post("/orders/{order_id}/pay", response_model=TicketOrderResponse)
async def pay_order(
    order_id: UUID,
    payload: PayOrderRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketOrderResponse:
    order = await pay_ticket_order(
        session,
        order_id=order_id,
        user=current_user,
        idempotency_key=payload.idempotency_key,
    )
    return order_response(order)


@router.post("/orders/{order_id}/refund", response_model=TicketOrderResponse)
async def refund_order(
    order_id: UUID,
    payload: RefundOrderRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketOrderResponse:
    order = await refund_ticket_order(
        session,
        order_id=order_id,
        user=current_user,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return order_response(order)


@router.post("/orders/{order_id}/reschedule", response_model=TicketOrderResponse)
async def reschedule_order(
    order_id: UUID,
    payload: RescheduleOrderRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketOrderResponse:
    order = await reschedule_ticket_order(
        session,
        order_id=order_id,
        user=current_user,
        target_slot_id=payload.target_slot_id,
        idempotency_key=payload.idempotency_key,
    )
    return order_response(order)


@router.get("/tickets/{ticket_id}/qr", response_model=TicketQrResponse)
async def ticket_qr(
    ticket_id: UUID,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TicketQrResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return await create_ticket_qr_response(
        session,
        ticket_id=ticket_id,
        user=current_user,
        settings=request.app.state.settings,
    )


@router.post("/gate/validate", response_model=GateValidationResponse)
async def gate_validate(
    payload: GateValidationRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GateValidationResponse:
    return await validate_ticket_at_gate(
        session,
        qr_data=payload.qr_data,
        request_id=payload.request_id,
        gate_code=payload.gate_code,
        validator=current_user,
        settings=request.app.state.settings,
    )

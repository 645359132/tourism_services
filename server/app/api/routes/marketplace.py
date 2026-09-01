"""Experience, reservations, queues, hospitality, reviews, and queue WebSocket."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_tourist
from app.core.errors import AppError
from app.db.models.user import User
from app.db.session import get_session
from app.realtime.queues import QueueConnectionHub, QueueTicketStore
from app.schemas.marketplace import (
    AvailabilityResponse,
    BundleBookingRequest,
    CancelReservationRequest,
    CreateFastPassRequest,
    CreateReservationRequest,
    DiningBookingRequest,
    ExperienceListResponse,
    ExperienceSessionListResponse,
    FastPassResponse,
    JoinQueueRequest,
    OfferListResponse,
    QueueResponse,
    ReservationListResponse,
    ReservationOperationRequest,
    ReservationResponse,
    ReviewRequest,
    ReviewResponse,
    StayBookingRequest,
    VenueListResponse,
    WsTicketRequest,
    WsTicketResponse,
)
from app.services.hospitality import (
    book_bundle,
    book_dining,
    book_stay,
    create_review,
    list_availability,
    list_offers,
    list_venues,
    review_response,
)
from app.services.queues import (
    ACTIVE_QUEUE_STATUSES,
    buy_fast_pass,
    fast_pass_response,
    get_queue,
    get_queue_by_identity,
    join_queue,
    leave_queue,
    queue_envelope,
    queue_response,
)
from app.services.reservations import (
    cancel_reservation,
    confirm_reservation,
    create_experience_reservation,
    list_experience_sessions,
    list_experiences,
    list_reservations,
    reservation_response,
)

router = APIRouter(tags=["marketplace"])


@router.get("/experiences", response_model=ExperienceListResponse)
async def experiences(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ExperienceListResponse:
    return ExperienceListResponse(items=await list_experiences(session))


@router.get(
    "/experiences/{experience_id}/sessions",
    response_model=ExperienceSessionListResponse,
)
async def experience_sessions(
    experience_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    visit_date: Annotated[date, Query(alias="date")],
) -> ExperienceSessionListResponse:
    return ExperienceSessionListResponse(
        items=await list_experience_sessions(
            session,
            experience_id=experience_id,
            visit_date=visit_date,
        )
    )


@router.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    payload: CreateReservationRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationResponse:
    reservation = await create_experience_reservation(
        session,
        user=current_user,
        session_id=payload.session_id,
        party_size=payload.party_size,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return reservation_response(reservation)


@router.get("/reservations", response_model=ReservationListResponse)
async def reservations(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationListResponse:
    found = await list_reservations(session, user=current_user)
    return ReservationListResponse(items=[reservation_response(item) for item in found])


@router.post(
    "/reservations/{reservation_id}/confirm",
    response_model=ReservationResponse,
)
async def confirm_booking(
    reservation_id: UUID,
    payload: ReservationOperationRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationResponse:
    reservation = await confirm_reservation(
        session,
        reservation_id=reservation_id,
        user=current_user,
        idempotency_key=payload.idempotency_key,
    )
    return reservation_response(reservation)


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
)
async def cancel_booking(
    reservation_id: UUID,
    payload: CancelReservationRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationResponse:
    reservation = await cancel_reservation(
        session,
        reservation_id=reservation_id,
        user=current_user,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
    )
    return reservation_response(reservation)


@router.post(
    "/queues",
    response_model=QueueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_queue(
    payload: JoinQueueRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueResponse:
    context = await join_queue(
        session,
        user=current_user,
        experience_id=payload.experience_id,
        party_size=payload.party_size,
        itinerary_id=payload.itinerary_id,
        idempotency_key=payload.idempotency_key,
    )
    return await queue_response(session, context)


@router.get("/queues/{queue_id}", response_model=QueueResponse)
async def queue_detail(
    queue_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueResponse:
    return await queue_response(
        session,
        await get_queue(session, queue_id=queue_id, user=current_user),
    )


@router.delete("/queues/{queue_id}", response_model=QueueResponse)
async def remove_queue(
    queue_id: UUID,
    payload: ReservationOperationRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueResponse:
    response = await queue_response(
        session,
        await leave_queue(
            session,
            queue_id=queue_id,
            user=current_user,
            idempotency_key=payload.idempotency_key,
        ),
    )
    await request.app.state.queue_hub.broadcast(queue_id, queue_envelope(response))
    return response


@router.post("/queues/{queue_id}/fast-pass", response_model=FastPassResponse)
async def create_fast_pass(
    queue_id: UUID,
    payload: CreateFastPassRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FastPassResponse:
    context = await buy_fast_pass(
        session,
        queue_id=queue_id,
        user=current_user,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    response = await queue_response(session, context)
    await request.app.state.queue_hub.broadcast(queue_id, queue_envelope(response))
    assert context.fast_pass is not None
    return fast_pass_response(context.fast_pass, context.experience)


@router.post("/ws-tickets", response_model=WsTicketResponse)
async def create_ws_ticket(
    payload: WsTicketRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WsTicketResponse:
    context = await get_queue(session, queue_id=payload.channel_id, user=current_user)
    if context.entry.status not in ACTIVE_QUEUE_STATUSES:
        raise AppError(
            status_code=409,
            code="QUEUE_NOT_ACTIVE",
            message="WebSocket tickets require an active queue",
        )
    store: QueueTicketStore = request.app.state.queue_tickets
    ticket, expires_at = await store.issue(
        user_id=current_user.id,
        queue_id=payload.channel_id,
    )
    return WsTicketResponse(ticket=ticket, expires_at=expires_at)


@router.websocket("/ws/queues/{queue_id}")
async def queue_websocket(
    websocket: WebSocket,
    queue_id: UUID,
    ticket: Annotated[str, Query(min_length=20, max_length=256)],
) -> None:
    store: QueueTicketStore = websocket.app.state.queue_tickets
    grant = await store.consume(token=ticket, queue_id=queue_id)
    if grant is None:
        await websocket.close(code=4401)
        return
    hub: QueueConnectionHub = websocket.app.state.queue_hub
    connection_id, messages = hub.register(queue_id)
    publisher = websocket.app.state.queue_publisher
    factory = publisher.session_factory_provider()
    try:
        async with factory() as session:
            context = await get_queue_by_identity(
                session,
                queue_id=queue_id,
                actor_id=grant.user_id,
            )
            if context.entry.status not in ACTIVE_QUEUE_STATUSES:
                hub.unregister(queue_id, connection_id)
                await websocket.close(code=4409)
                return
            initial = queue_envelope(await queue_response(session, context))
    except AppError:
        hub.unregister(queue_id, connection_id)
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await websocket.send_json(initial.model_dump(mode="json"))

    async def send_updates() -> None:
        while True:
            envelope = await messages.get()
            try:
                await asyncio.wait_for(
                    websocket.send_json(envelope.model_dump(mode="json")),
                    timeout=2.0,
                )
                if envelope.data.queue.status not in ACTIVE_QUEUE_STATUSES:
                    with suppress(RuntimeError):
                        await websocket.close(code=1000)
                    return
            except (TimeoutError, RuntimeError):
                with suppress(RuntimeError):
                    await websocket.close(code=1013)
                return

    async def receive_pings() -> None:
        while True:
            try:
                message = await websocket.receive_json()
            except ValueError:
                with suppress(RuntimeError):
                    await websocket.close(code=1003)
                return
            if message.get("type") == "ping":
                continue
            with suppress(RuntimeError):
                await websocket.close(code=1008)
            return

    sender = asyncio.create_task(send_updates())
    receiver = asyncio.create_task(receive_pings())
    try:
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
                await task
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        receiver.cancel()
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await sender
        with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await receiver
        hub.unregister(queue_id, connection_id)


@router.get("/hospitality/venues", response_model=VenueListResponse)
async def hospitality_venues(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VenueListResponse:
    return VenueListResponse(items=await list_venues(session))


@router.get("/hospitality/offers", response_model=OfferListResponse)
async def hospitality_offers(
    session: Annotated[AsyncSession, Depends(get_session)],
    venue_id: Annotated[UUID | None, Query()] = None,
) -> OfferListResponse:
    return OfferListResponse(items=await list_offers(session, venue_id=venue_id))


@router.get("/hospitality/availability", response_model=AvailabilityResponse)
async def hospitality_availability(
    session: Annotated[AsyncSession, Depends(get_session)],
    resource_id: Annotated[UUID, Query()],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
) -> AvailabilityResponse:
    return AvailabilityResponse(
        items=await list_availability(
            session,
            resource_id=resource_id,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.post(
    "/hospitality/bookings/stay",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_stay_booking(
    payload: StayBookingRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationResponse:
    reservation = await book_stay(
        session,
        user=current_user,
        offer_id=payload.offer_id,
        check_in=payload.check_in,
        check_out=payload.check_out,
        quantity=payload.quantity,
        party_size=payload.party_size,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return reservation_response(reservation)


@router.post(
    "/hospitality/bookings/dining",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dining_booking(
    payload: DiningBookingRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationResponse:
    reservation = await book_dining(
        session,
        user=current_user,
        offer_id=payload.offer_id,
        starts_at=payload.starts_at,
        party_size=payload.party_size,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return reservation_response(reservation)


@router.post(
    "/hospitality/bookings/bundle",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bundle_booking(
    payload: BundleBookingRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationResponse:
    reservation = await book_bundle(
        session,
        user=current_user,
        offer_id=payload.offer_id,
        visit_date=payload.visit_date,
        party_size=payload.party_size,
        idempotency_key=payload.idempotency_key,
        settings=request.app.state.settings,
    )
    return reservation_response(reservation)


@router.post(
    "/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    payload: ReviewRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReviewResponse:
    review = await create_review(
        session,
        user=current_user,
        reservation_id=payload.reservation_id,
        rating=payload.rating,
        content=payload.content,
    )
    return review_response(review)

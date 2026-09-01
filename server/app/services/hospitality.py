"""Hospitality catalogs, multi-bucket bookings, bundles, and reviews."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.db.models.marketplace import (
    RESERVATION_CONFIRMED,
    BundleComponent,
    ExperienceSession,
    HospitalityOffer,
    HospitalityVenue,
    InventoryBucket,
    Review,
)
from app.db.models.user import User
from app.schemas.marketplace import (
    AvailabilityItemResponse,
    BundleComponentResponse,
    OfferResponse,
    ReviewResponse,
    VenueResponse,
)
from app.services.reservations import (
    AllocationSpec,
    _aware,
    _error,
    _owned_reservation,
    _scenic_datetime,
    create_reservation_from_allocations,
    expire_reservation_holds,
)


def venue_response(venue: HospitalityVenue) -> VenueResponse:
    return VenueResponse(
        id=str(venue.id),
        code=venue.code,
        kind=venue.kind,
        name=venue.name,
        description=venue.description,
        address=venue.address,
        node_id=str(venue.node_id),
        accessibility=venue.accessibility,
        amenities=venue.amenities,
        rating=venue.rating_tenths / 10,
        is_demo=venue.is_demo,
    )


def offer_response(offer: HospitalityOffer) -> OfferResponse:
    attributes = [
        f"最多 {offer.max_party_size} 人",
        f"每时段 {offer.capacity_per_bucket} 份",
        *offer.venue.amenities,
    ]
    return OfferResponse(
        id=str(offer.id),
        venue_id=str(offer.venue_id),
        code=offer.code,
        kind=offer.kind,
        name=offer.name,
        description=offer.description,
        base_price_cents=offer.unit_price_cents,
        capacity=offer.capacity_per_bucket,
        max_party_size=offer.max_party_size,
        is_demo=offer.venue.is_demo,
        bundle_components=[
            BundleComponentResponse(
                kind=component.component_type,
                ref_id=str(component.component_resource_id),
                name=component.component_name,
                quantity=component.quantity,
                offset_minutes=component.offset_minutes,
            )
            for component in offer.bundle_components
        ],
        attributes=list(dict.fromkeys(attributes)),
    )


def review_response(review: Review) -> ReviewResponse:
    return ReviewResponse(
        id=str(review.id),
        reservation_id=str(review.reservation_id),
        target_type=review.target_type,
        target_id=str(review.target_id),
        rating=review.rating,
        content=review.content,
        status=review.status,
        created_at=_aware(review.created_at),
    )


async def list_venues(session: AsyncSession) -> list[VenueResponse]:
    venues = list(await session.scalars(select(HospitalityVenue).order_by(HospitalityVenue.code)))
    return [venue_response(venue) for venue in venues]


async def list_offers(
    session: AsyncSession,
    *,
    venue_id: UUID | None = None,
) -> list[OfferResponse]:
    statement = (
        select(HospitalityOffer)
        .options(
            selectinload(HospitalityOffer.bundle_components),
            selectinload(HospitalityOffer.venue),
        )
        .where(HospitalityOffer.is_active.is_(True))
        .order_by(HospitalityOffer.code)
    )
    if venue_id is not None:
        statement = statement.where(HospitalityOffer.venue_id == venue_id)
    offers = list(await session.scalars(statement))
    return [offer_response(offer) for offer in offers]


async def list_availability(
    session: AsyncSession,
    *,
    resource_id: UUID,
    date_from: date,
    date_to: date,
) -> list[AvailabilityItemResponse]:
    if date_to < date_from or (date_to - date_from).days > 31:
        raise _error(422, "INVALID_DATE_RANGE", "Availability range must be 0 to 31 days")
    await expire_reservation_holds(session)
    await session.commit()
    offer = await session.scalar(
        select(HospitalityOffer)
        .options(selectinload(HospitalityOffer.bundle_components))
        .where(HospitalityOffer.id == resource_id, HospitalityOffer.is_active.is_(True))
    )
    if offer is None:
        raise _error(404, "OFFER_NOT_FOUND", "Hospitality offer not found")
    resource_ids = [offer.id]
    if offer.kind == "BUNDLE":
        resource_ids = [
            component.component_resource_id
            for component in offer.bundle_components
            if component.component_type in {"ROOM", "MEAL"}
        ]
    buckets = list(
        await session.scalars(
            select(InventoryBucket)
            .where(
                InventoryBucket.resource_id.in_(resource_ids),
                InventoryBucket.business_date >= date_from,
                InventoryBucket.business_date <= date_to,
            )
            .order_by(InventoryBucket.starts_at)
        )
    )
    return [
        AvailabilityItemResponse(
            bucket_id=str(bucket.id),
            resource_type=bucket.resource_type,
            resource_id=str(bucket.resource_id),
            business_date=bucket.business_date,
            start_at=_aware(bucket.starts_at),
            end_at=_aware(bucket.ends_at),
            remaining=max(bucket.capacity - bucket.held - bucket.confirmed, 0),
            unit_price_cents=offer.unit_price_cents,
        )
        for bucket in buckets
    ]


async def _get_offer(
    session: AsyncSession,
    *,
    offer_id: UUID,
    expected_kind: str,
) -> HospitalityOffer:
    offer = await session.scalar(
        select(HospitalityOffer)
        .options(
            selectinload(HospitalityOffer.bundle_components),
            selectinload(HospitalityOffer.venue),
        )
        .where(HospitalityOffer.id == offer_id, HospitalityOffer.is_active.is_(True))
    )
    if offer is None:
        raise _error(404, "OFFER_NOT_FOUND", "Hospitality offer not found")
    if offer.kind != expected_kind:
        raise _error(409, "OFFER_KIND_MISMATCH", f"Offer is not a {expected_kind} offer")
    return offer


async def book_stay(
    session: AsyncSession,
    *,
    user: User,
    offer_id: UUID,
    check_in: date,
    check_out: date,
    quantity: int,
    party_size: int,
    idempotency_key: str,
    settings: Settings,
):
    offer = await _get_offer(session, offer_id=offer_id, expected_kind="ROOM")
    nights = (check_out - check_in).days
    if nights < 1 or nights > 30:
        raise _error(422, "INVALID_STAY_RANGE", "Stay must contain 1 to 30 nights")
    if _scenic_datetime(check_in, time(15)) <= datetime.now(UTC):
        raise _error(409, "BOOKING_WINDOW_CLOSED", "Stay check-in has already started")
    if party_size > offer.max_party_size * quantity:
        raise _error(422, "PARTY_TOO_LARGE", "Party exceeds room occupancy")
    dates = [check_in + timedelta(days=index) for index in range(nights)]
    buckets = list(
        await session.scalars(
            select(InventoryBucket)
            .where(
                InventoryBucket.resource_type == "ROOM",
                InventoryBucket.resource_id == offer.id,
                InventoryBucket.business_date.in_(dates),
            )
            .order_by(InventoryBucket.business_date)
        )
    )
    if [bucket.business_date for bucket in buckets] != dates:
        raise _error(409, "INVENTORY_UNAVAILABLE", "One or more room nights are unavailable")
    return await create_reservation_from_allocations(
        session,
        user=user,
        kind="STAY",
        resource_type="ROOM",
        resource_id=offer.id,
        resource_name=offer.name,
        starts_at=_scenic_datetime(check_in, time(15)),
        ends_at=_scenic_datetime(check_out, time(11)),
        party_size=party_size,
        quantity=quantity,
        total_cents=offer.unit_price_cents * quantity * nights,
        idempotency_key=idempotency_key,
        request_payload={
            "check_in": check_in,
            "check_out": check_out,
            "offer_id": str(offer_id),
            "party_size": party_size,
            "quantity": quantity,
        },
        specs=[AllocationSpec(bucket, quantity) for bucket in buckets],
        settings=settings,
    )


async def book_dining(
    session: AsyncSession,
    *,
    user: User,
    offer_id: UUID,
    starts_at: datetime,
    party_size: int,
    idempotency_key: str,
    settings: Settings,
):
    offer = await _get_offer(session, offer_id=offer_id, expected_kind="MEAL")
    if party_size > offer.max_party_size:
        raise _error(422, "PARTY_TOO_LARGE", "Party exceeds dining offer capacity")
    requested_start = _aware(starts_at)
    buckets = list(
        await session.scalars(
            select(InventoryBucket).where(
                InventoryBucket.resource_type == "MEAL",
                InventoryBucket.resource_id == offer.id,
            )
        )
    )
    bucket = next(
        (candidate for candidate in buckets if _aware(candidate.starts_at) == requested_start),
        None,
    )
    if bucket is None:
        raise _error(409, "INVENTORY_UNAVAILABLE", "Dining slot is unavailable")
    if _aware(bucket.ends_at) <= datetime.now(UTC):
        raise _error(409, "BOOKING_WINDOW_CLOSED", "Dining slot has already ended")
    return await create_reservation_from_allocations(
        session,
        user=user,
        kind="DINING",
        resource_type="MEAL",
        resource_id=offer.id,
        resource_name=offer.name,
        starts_at=bucket.starts_at,
        ends_at=bucket.ends_at,
        party_size=party_size,
        quantity=party_size,
        total_cents=offer.unit_price_cents * party_size,
        idempotency_key=idempotency_key,
        request_payload={
            "offer_id": str(offer_id),
            "party_size": party_size,
            "starts_at": requested_start.isoformat(),
        },
        specs=[AllocationSpec(bucket, party_size)],
        settings=settings,
    )


async def _bundle_component_bucket(
    session: AsyncSession,
    *,
    component: BundleComponent,
    visit_date: date,
) -> InventoryBucket:
    if component.component_type in {"ROOM", "MEAL"}:
        bucket = await session.scalar(
            select(InventoryBucket)
            .where(
                InventoryBucket.resource_type == component.component_type,
                InventoryBucket.resource_id == component.component_resource_id,
                InventoryBucket.business_date == visit_date,
            )
            .order_by(InventoryBucket.starts_at)
        )
    elif component.component_type == "EXPERIENCE":
        bucket = await session.scalar(
            select(InventoryBucket)
            .join(
                ExperienceSession,
                (InventoryBucket.resource_type == "EXPERIENCE_SESSION")
                & (InventoryBucket.resource_id == ExperienceSession.id),
            )
            .where(
                ExperienceSession.experience_id == component.component_resource_id,
                InventoryBucket.business_date == visit_date,
                ExperienceSession.status == "OPEN",
            )
            .order_by(InventoryBucket.starts_at)
        )
    else:
        raise _error(409, "BUNDLE_INVALID", "Bundle contains an unsupported component")
    if bucket is None:
        raise _error(
            409,
            "INVENTORY_UNAVAILABLE",
            f"Bundle component {component.component_name} is unavailable",
        )
    return bucket


async def book_bundle(
    session: AsyncSession,
    *,
    user: User,
    offer_id: UUID,
    visit_date: date,
    party_size: int,
    idempotency_key: str,
    settings: Settings,
):
    offer = await _get_offer(session, offer_id=offer_id, expected_kind="BUNDLE")
    if not offer.bundle_components:
        raise _error(409, "BUNDLE_INVALID", "Bundle has no inventory components")
    if party_size > offer.max_party_size:
        raise _error(422, "PARTY_TOO_LARGE", "Party exceeds bundle capacity")
    specs: list[AllocationSpec] = []
    for component in offer.bundle_components:
        bucket = await _bundle_component_bucket(
            session,
            component=component,
            visit_date=visit_date,
        )
        allocation_quantity = (
            component.quantity
            if component.component_type == "ROOM"
            else party_size * component.quantity
        )
        specs.append(AllocationSpec(bucket, allocation_quantity))
    if any(_aware(spec.bucket.ends_at) <= datetime.now(UTC) for spec in specs):
        raise _error(409, "BOOKING_WINDOW_CLOSED", "A bundle component has already ended")
    starts_at = min(_aware(spec.bucket.starts_at) for spec in specs)
    ends_at = max(_aware(spec.bucket.ends_at) for spec in specs)
    return await create_reservation_from_allocations(
        session,
        user=user,
        kind="BUNDLE",
        resource_type="BUNDLE",
        resource_id=offer.id,
        resource_name=offer.name,
        starts_at=starts_at,
        ends_at=ends_at,
        party_size=party_size,
        quantity=1,
        total_cents=offer.unit_price_cents * party_size,
        idempotency_key=idempotency_key,
        request_payload={
            "offer_id": str(offer_id),
            "party_size": party_size,
            "visit_date": visit_date,
        },
        specs=specs,
        settings=settings,
    )


async def create_review(
    session: AsyncSession,
    *,
    user: User,
    reservation_id: UUID,
    rating: int,
    content: str,
) -> Review:
    actor_id = user.id
    reservation = await _owned_reservation(session, reservation_id=reservation_id, user=user)
    now = datetime.now(UTC)
    if reservation.status == RESERVATION_CONFIRMED and _aware(reservation.ends_at) <= now:
        reservation.status = "COMPLETED"
        reservation.completed_at = now
        reservation.version += 1
        for allocation in reservation.allocations:
            allocation.status = "COMPLETED"
    elif reservation.status != "COMPLETED":
        raise _error(409, "REVIEW_NOT_ALLOWED", "Only completed visits can be reviewed")
    existing = await session.scalar(
        select(Review).where(
            Review.user_id == actor_id,
            Review.reservation_id == reservation_id,
        )
    )
    if existing is not None:
        raise _error(409, "REVIEW_ALREADY_EXISTS", "Reservation was already reviewed")
    review = Review(
        user_id=actor_id,
        reservation_id=reservation.id,
        target_type=reservation.resource_type,
        target_id=reservation.resource_id,
        rating=rating,
        content=content.strip(),
    )
    session.add(review)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        existing = await session.scalar(
            select(Review).where(
                Review.user_id == actor_id,
                Review.reservation_id == reservation_id,
            )
        )
        if existing is not None:
            raise _error(
                409,
                "REVIEW_ALREADY_EXISTS",
                "Reservation was already reviewed",
            ) from exc
        raise
    await session.refresh(review)
    return review

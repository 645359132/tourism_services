"""Transactional experience and hospitality reservations over shared inventory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models.marketplace import (
    RESERVATION_CANCELLED,
    RESERVATION_CONFIRMED,
    RESERVATION_EXPIRED,
    RESERVATION_HELD,
    Experience,
    ExperienceSession,
    InventoryBucket,
    Reservation,
    ReservationAllocation,
    UserScheduleLock,
)
from app.db.models.ticketing import (
    ORDER_PAID,
    ORDER_PENDING_PAYMENT,
    TicketOrder,
    TicketOrderItem,
)
from app.db.models.user import User
from app.schemas.marketplace import (
    ExperienceResponse,
    ExperienceSessionResponse,
    ReservationAllocationResponse,
    ReservationResponse,
)

SCENIC_TIMEZONE = ZoneInfo("Asia/Shanghai")
ACTIVE_RESERVATION_STATUSES = (RESERVATION_HELD, RESERVATION_CONFIRMED)


@dataclass(frozen=True, slots=True)
class AllocationSpec:
    bucket: InventoryBucket
    quantity: int


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


def _scenic_datetime(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=SCENIC_TIMEZONE).astimezone(UTC)


def _overlaps(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
    *,
    buffer_minutes: int = 0,
) -> bool:
    buffer = timedelta(minutes=buffer_minutes)
    return first_start < second_end + buffer and second_start < first_end + buffer


def experience_response(experience: Experience) -> ExperienceResponse:
    return ExperienceResponse(
        id=str(experience.id),
        code=experience.code,
        kind=experience.kind,
        name=experience.name,
        description=experience.description,
        node_id=str(experience.node_id),
        duration_minutes=experience.duration_minutes,
        min_height_cm=experience.min_height_cm or 0,
        fastpass_allowed=experience.fastpass_allowed,
        fastpass_price_cents=experience.fastpass_price_cents,
        accessibility=experience.accessibility,
        wait_minutes=experience.wait_minutes,
    )


def reservation_response(reservation: Reservation) -> ReservationResponse:
    return ReservationResponse(
        id=str(reservation.id),
        booking_no=reservation.booking_no,
        kind=reservation.kind,
        resource_type=reservation.resource_type,
        resource_id=str(reservation.resource_id),
        resource_name=reservation.resource_name,
        starts_at=_aware(reservation.starts_at),
        ends_at=_aware(reservation.ends_at),
        party_size=reservation.party_size,
        quantity=reservation.quantity,
        total_cents=reservation.total_cents,
        status=reservation.status,
        provider=reservation.provider,
        is_demo=reservation.is_demo,
        allocations=[
            ReservationAllocationResponse(
                bucket_id=str(allocation.bucket_id),
                business_date=allocation.business_date,
                starts_at=_aware(allocation.starts_at),
                ends_at=_aware(allocation.ends_at),
                quantity=allocation.quantity,
            )
            for allocation in reservation.allocations
        ],
    )


async def _load_reservation(
    session: AsyncSession,
    reservation_id: UUID,
) -> Reservation | None:
    return await session.scalar(
        select(Reservation)
        .execution_options(populate_existing=True)
        .options(selectinload(Reservation.allocations))
        .where(Reservation.id == reservation_id)
    )


async def _owned_reservation(
    session: AsyncSession,
    *,
    reservation_id: UUID,
    user: User,
) -> Reservation:
    reservation = await _load_reservation(session, reservation_id)
    if reservation is None:
        raise _error(404, "RESERVATION_NOT_FOUND", "Reservation not found")
    if reservation.user_id != user.id and "admin" not in user.role_names:
        raise _error(404, "RESERVATION_NOT_FOUND", "Reservation not found")
    return reservation


async def _owned_reservation_by_identity(
    session: AsyncSession,
    *,
    reservation_id: UUID,
    actor_id: UUID,
    actor_is_admin: bool,
) -> Reservation:
    reservation = await _load_reservation(session, reservation_id)
    if reservation is None or (reservation.user_id != actor_id and not actor_is_admin):
        raise _error(404, "RESERVATION_NOT_FOUND", "Reservation not found")
    return reservation


async def acquire_user_schedule_lock(session: AsyncSession, user_id: UUID) -> None:
    """Serialize one user's cross-resource conflict check and reservation insert."""

    bind = session.get_bind()
    values = {"user_id": user_id, "version": 1}
    if bind.dialect.name == "sqlite":
        statement = sqlite_insert(UserScheduleLock).values(**values).on_conflict_do_nothing()
        await session.execute(statement)
    elif bind.dialect.name == "postgresql":
        statement = (
            postgresql_insert(UserScheduleLock)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[UserScheduleLock.user_id])
        )
        await session.execute(statement)
    elif await session.get(UserScheduleLock, user_id) is None:
        session.add(UserScheduleLock(**values))
        await session.flush()

    locked = await session.execute(
        update(UserScheduleLock)
        .execution_options(synchronize_session=False)
        .where(UserScheduleLock.user_id == user_id)
        .values(version=UserScheduleLock.version + 1)
    )
    if locked.rowcount != 1:
        raise RuntimeError("User schedule lock could not be acquired")


async def _release_allocations(
    session: AsyncSession,
    reservation: Reservation,
    *,
    source_status: str,
    target_status: str,
) -> None:
    counter_column = (
        InventoryBucket.held if source_status == RESERVATION_HELD else InventoryBucket.confirmed
    )
    for allocation in sorted(reservation.allocations, key=lambda item: str(item.bucket_id)):
        released = await session.execute(
            update(InventoryBucket)
            .execution_options(synchronize_session=False)
            .where(
                InventoryBucket.id == allocation.bucket_id,
                counter_column >= allocation.quantity,
            )
            .values(
                {
                    counter_column: counter_column - allocation.quantity,
                    InventoryBucket.version: InventoryBucket.version + 1,
                }
            )
        )
        if released.rowcount != 1:
            raise RuntimeError("Reservation inventory ledger is inconsistent")
        allocation.status = target_status


async def expire_reservation_holds(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
) -> int:
    now = datetime.now(UTC)
    statement = (
        select(Reservation)
        .options(selectinload(Reservation.allocations))
        .where(
            Reservation.status == RESERVATION_HELD,
            Reservation.hold_expires_at <= now,
        )
        .limit(100)
    )
    if user_id is not None:
        statement = statement.where(Reservation.user_id == user_id)
    reservations = list(await session.scalars(statement))
    expired = 0
    for reservation in reservations:
        transitioned = await session.execute(
            update(Reservation)
            .execution_options(synchronize_session=False)
            .where(
                Reservation.id == reservation.id,
                Reservation.status == RESERVATION_HELD,
                Reservation.version == reservation.version,
                Reservation.hold_expires_at <= now,
            )
            .values(
                status=RESERVATION_EXPIRED,
                version=Reservation.version + 1,
            )
        )
        if transitioned.rowcount != 1:
            continue
        await _release_allocations(
            session,
            reservation,
            source_status=RESERVATION_HELD,
            target_status=RESERVATION_EXPIRED,
        )
        expired += 1
    return expired


async def check_marketplace_schedule_conflict(
    session: AsyncSession,
    *,
    user_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    buffer_minutes: int,
) -> None:
    starts_at = _aware(starts_at)
    ends_at = _aware(ends_at)
    reservations = list(
        await session.scalars(
            select(Reservation)
            .options(selectinload(Reservation.allocations))
            .where(
                Reservation.user_id == user_id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
        )
    )
    bucket_ids = {
        allocation.bucket_id
        for reservation in reservations
        for allocation in reservation.allocations
    }
    buckets = {
        bucket.id: bucket
        for bucket in (
            list(
                await session.scalars(
                    select(InventoryBucket).where(InventoryBucket.id.in_(bucket_ids))
                )
            )
            if bucket_ids
            else []
        )
    }
    for reservation in reservations:
        room_allocations = [
            allocation
            for allocation in reservation.allocations
            if buckets[allocation.bucket_id].resource_type == "ROOM"
        ]
        timed_allocations = [
            allocation
            for allocation in reservation.allocations
            if buckets[allocation.bucket_id].resource_type != "ROOM"
        ]
        if room_allocations:
            lodging_start = min(_aware(item.starts_at) for item in room_allocations)
            lodging_end = max(_aware(item.ends_at) for item in room_allocations)
            milestones = (
                (lodging_start, min(lodging_start + timedelta(minutes=30), lodging_end)),
                (max(lodging_start, lodging_end - timedelta(minutes=30)), lodging_end),
            )
            if any(
                _overlaps(
                    starts_at,
                    ends_at,
                    milestone_start,
                    milestone_end,
                    buffer_minutes=buffer_minutes,
                )
                for milestone_start, milestone_end in milestones
            ):
                raise _error(
                    409,
                    "SCHEDULE_CONFLICT",
                    "Reservation conflicts with a stay check-in or checkout",
                )
        if any(
            _overlaps(
                starts_at,
                ends_at,
                _aware(allocation.starts_at),
                _aware(allocation.ends_at),
                buffer_minutes=buffer_minutes,
            )
            for allocation in timed_allocations
        ):
            raise _error(409, "SCHEDULE_CONFLICT", "Reservation conflicts with an active booking")


async def _check_schedule_conflict(
    session: AsyncSession,
    *,
    user_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    buffer_minutes: int,
) -> None:
    await check_marketplace_schedule_conflict(
        session,
        user_id=user_id,
        starts_at=starts_at,
        ends_at=ends_at,
        buffer_minutes=buffer_minutes,
    )
    await check_ticket_schedule_conflict(
        session,
        user_id=user_id,
        starts_at=starts_at,
        ends_at=ends_at,
        buffer_minutes=buffer_minutes,
    )


async def check_ticket_schedule_conflict(
    session: AsyncSession,
    *,
    user_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
    buffer_minutes: int,
    exclude_order_id: UUID | None = None,
) -> None:
    starts_at = _aware(starts_at)
    ends_at = _aware(ends_at)
    statement = (
        select(TicketOrder)
        .options(selectinload(TicketOrder.items).selectinload(TicketOrderItem.slot))
        .where(
            TicketOrder.user_id == user_id,
            TicketOrder.status.in_((ORDER_PENDING_PAYMENT, ORDER_PAID)),
        )
    )
    if exclude_order_id is not None:
        statement = statement.where(TicketOrder.id != exclude_order_id)
    orders = list(await session.scalars(statement))
    now = datetime.now(UTC)
    for order in orders:
        if order.status == ORDER_PENDING_PAYMENT and _aware(order.expires_at) <= now:
            continue
        for item in order.items:
            slot_start = _scenic_datetime(item.slot.visit_date, item.slot.start_time)
            slot_end = _scenic_datetime(item.slot.visit_date, item.slot.end_time)
            if item.slot.end_time <= item.slot.start_time:
                slot_end += timedelta(days=1)
            if _overlaps(
                starts_at,
                ends_at,
                slot_start,
                slot_end,
                buffer_minutes=buffer_minutes,
            ):
                raise _error(
                    409,
                    "SCHEDULE_CONFLICT",
                    "Reservation conflicts with an active ticket booking",
                )


async def _check_lodging_conflict(
    session: AsyncSession,
    *,
    user_id: UUID,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    reservations = list(
        await session.scalars(
            select(Reservation)
            .options(selectinload(Reservation.allocations))
            .where(
                Reservation.user_id == user_id,
                Reservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
        )
    )
    bucket_ids = {
        allocation.bucket_id
        for reservation in reservations
        for allocation in reservation.allocations
    }
    room_bucket_ids = set(
        await session.scalars(
            select(InventoryBucket.id).where(
                InventoryBucket.id.in_(bucket_ids),
                InventoryBucket.resource_type == "ROOM",
            )
        )
    )
    for reservation in reservations:
        room_allocations = [
            allocation
            for allocation in reservation.allocations
            if allocation.bucket_id in room_bucket_ids
        ]
        if not room_allocations:
            continue
        existing_start = min(_aware(item.starts_at) for item in room_allocations)
        existing_end = max(_aware(item.ends_at) for item in room_allocations)
        if _overlaps(
            _aware(starts_at),
            _aware(ends_at),
            existing_start,
            existing_end,
        ):
            raise _error(409, "SCHEDULE_CONFLICT", "Stay overlaps an active stay booking")


async def _check_allocation_conflicts(
    session: AsyncSession,
    *,
    user_id: UUID,
    specs: list[AllocationSpec],
    buffer_minutes: int,
) -> None:
    room_specs = [spec for spec in specs if spec.bucket.resource_type == "ROOM"]
    timed_specs = [spec for spec in specs if spec.bucket.resource_type != "ROOM"]
    if room_specs:
        lodging_start = min(_aware(spec.bucket.starts_at) for spec in room_specs)
        lodging_end = max(_aware(spec.bucket.ends_at) for spec in room_specs)
        await _check_lodging_conflict(
            session,
            user_id=user_id,
            starts_at=lodging_start,
            ends_at=lodging_end,
        )
        await _check_schedule_conflict(
            session,
            user_id=user_id,
            starts_at=lodging_start,
            ends_at=min(lodging_start + timedelta(minutes=30), lodging_end),
            buffer_minutes=buffer_minutes,
        )
        await _check_schedule_conflict(
            session,
            user_id=user_id,
            starts_at=max(lodging_start, lodging_end - timedelta(minutes=30)),
            ends_at=lodging_end,
            buffer_minutes=buffer_minutes,
        )
    for spec in timed_specs:
        await _check_schedule_conflict(
            session,
            user_id=user_id,
            starts_at=spec.bucket.starts_at,
            ends_at=spec.bucket.ends_at,
            buffer_minutes=buffer_minutes,
        )


async def _allocate_held(
    session: AsyncSession,
    specs: list[AllocationSpec],
) -> None:
    for spec in sorted(specs, key=lambda item: str(item.bucket.id)):
        allocated = await session.execute(
            update(InventoryBucket)
            .execution_options(synchronize_session=False)
            .where(
                InventoryBucket.id == spec.bucket.id,
                InventoryBucket.held + InventoryBucket.confirmed + spec.quantity
                <= InventoryBucket.capacity,
            )
            .values(
                held=InventoryBucket.held + spec.quantity,
                version=InventoryBucket.version + 1,
            )
        )
        if allocated.rowcount != 1:
            await session.rollback()
            raise _error(409, "INSUFFICIENT_INVENTORY", "Not enough shared inventory")


async def create_reservation_from_allocations(
    session: AsyncSession,
    *,
    user: User,
    kind: str,
    resource_type: str,
    resource_id: UUID,
    resource_name: str,
    starts_at: datetime,
    ends_at: datetime,
    party_size: int,
    quantity: int,
    total_cents: int,
    idempotency_key: str,
    request_payload: dict[str, object],
    specs: list[AllocationSpec],
    settings: Settings,
) -> Reservation:
    """Create one HELD reservation and all of its allocations in one transaction."""

    actor_id = user.id
    request_hash = _hash_payload(request_payload)
    existing = await session.scalar(
        select(Reservation).where(
            Reservation.user_id == actor_id,
            Reservation.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Idempotency key payload differs")
        loaded = await _load_reservation(session, existing.id)
        assert loaded is not None
        return loaded

    await expire_reservation_holds(session)
    await session.commit()
    await acquire_user_schedule_lock(session, actor_id)
    existing = await session.scalar(
        select(Reservation).where(
            Reservation.user_id == actor_id,
            Reservation.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Idempotency key payload differs")
        await session.commit()
        loaded = await _load_reservation(session, existing.id)
        assert loaded is not None
        return loaded

    await _check_allocation_conflicts(
        session,
        user_id=actor_id,
        specs=specs,
        buffer_minutes=settings.reservation_walking_buffer_minutes,
    )
    await _allocate_held(session, specs)
    reservation_id = uuid4()
    reservation = Reservation(
        id=reservation_id,
        booking_no=f"RSV-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:12].upper()}",
        user_id=actor_id,
        kind=kind,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        starts_at=_aware(starts_at),
        ends_at=_aware(ends_at),
        party_size=party_size,
        quantity=quantity,
        total_cents=total_cents,
        status=RESERVATION_HELD,
        provider="demo",
        is_demo=True,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        hold_expires_at=datetime.now(UTC) + timedelta(minutes=settings.reservation_hold_minutes),
    )
    reservation.allocations.extend(
        ReservationAllocation(
            bucket_id=spec.bucket.id,
            business_date=spec.bucket.business_date,
            starts_at=_aware(spec.bucket.starts_at),
            ends_at=_aware(spec.bucket.ends_at),
            quantity=spec.quantity,
            status=RESERVATION_HELD,
        )
        for spec in specs
    )
    session.add(reservation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(Reservation).where(
                Reservation.user_id == actor_id,
                Reservation.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Idempotency key payload differs") from exc
        reservation_id = concurrent.id
    loaded = await _load_reservation(session, reservation_id)
    assert loaded is not None
    return loaded


async def list_experiences(session: AsyncSession) -> list[ExperienceResponse]:
    experiences = list(
        await session.scalars(
            select(Experience).where(Experience.is_active.is_(True)).order_by(Experience.code)
        )
    )
    return [experience_response(experience) for experience in experiences]


async def list_experience_sessions(
    session: AsyncSession,
    *,
    experience_id: UUID,
    visit_date: date,
) -> list[ExperienceSessionResponse]:
    await expire_reservation_holds(session)
    await session.commit()
    experience = await session.get(Experience, experience_id)
    if experience is None or not experience.is_active:
        raise _error(404, "EXPERIENCE_NOT_FOUND", "Experience not found")
    session_rows = list(
        await session.execute(
            select(ExperienceSession, InventoryBucket)
            .join(
                InventoryBucket,
                (InventoryBucket.resource_type == "EXPERIENCE_SESSION")
                & (InventoryBucket.resource_id == ExperienceSession.id),
            )
            .where(
                ExperienceSession.experience_id == experience_id,
                InventoryBucket.business_date == visit_date,
            )
            .order_by(ExperienceSession.starts_at)
        )
    )
    return [
        ExperienceSessionResponse(
            id=str(experience_session.id),
            experience_id=str(experience.id),
            experience_name=experience.name,
            starts_at=_aware(experience_session.starts_at),
            ends_at=_aware(experience_session.ends_at),
            capacity=experience_session.capacity,
            remaining=max(bucket.capacity - bucket.held - bucket.confirmed, 0),
            status=experience_session.status,
        )
        for experience_session, bucket in session_rows
    ]


async def create_experience_reservation(
    session: AsyncSession,
    *,
    user: User,
    session_id: UUID,
    party_size: int,
    idempotency_key: str,
    settings: Settings,
) -> Reservation:
    experience_session = await session.get(ExperienceSession, session_id)
    if experience_session is None:
        raise _error(404, "SESSION_NOT_FOUND", "Experience session not found")
    experience = await session.get(Experience, experience_session.experience_id)
    assert experience is not None
    if experience_session.status != "OPEN" or _aware(experience_session.starts_at) <= datetime.now(
        UTC
    ):
        raise _error(409, "SESSION_CLOSED", "Experience session is closed")
    bucket = await session.scalar(
        select(InventoryBucket).where(
            InventoryBucket.resource_type == "EXPERIENCE_SESSION",
            InventoryBucket.resource_id == experience_session.id,
        )
    )
    if bucket is None:
        raise _error(409, "INVENTORY_UNAVAILABLE", "Experience inventory is unavailable")
    return await create_reservation_from_allocations(
        session,
        user=user,
        kind="EXPERIENCE",
        resource_type="EXPERIENCE_SESSION",
        resource_id=experience_session.id,
        resource_name=experience.name,
        starts_at=experience_session.starts_at,
        ends_at=experience_session.ends_at,
        party_size=party_size,
        quantity=party_size,
        total_cents=0,
        idempotency_key=idempotency_key,
        request_payload={"party_size": party_size, "session_id": str(session_id)},
        specs=[AllocationSpec(bucket, party_size)],
        settings=settings,
    )


async def list_reservations(
    session: AsyncSession,
    *,
    user: User,
    offset: int,
    limit: int,
) -> tuple[list[Reservation], int]:
    await expire_reservation_holds(
        session,
        user_id=None if "admin" in user.role_names else user.id,
    )
    await session.commit()
    statement = (
        select(Reservation)
        .execution_options(populate_existing=True)
        .options(selectinload(Reservation.allocations))
        .order_by(Reservation.created_at.desc(), Reservation.id.desc())
    )
    if "admin" not in user.role_names:
        statement = statement.where(Reservation.user_id == user.id)
    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    return list(await session.scalars(statement.offset(offset).limit(limit))), total


async def confirm_reservation(
    session: AsyncSession,
    *,
    reservation_id: UUID,
    user: User,
    idempotency_key: str,
) -> Reservation:
    actor_id = user.id
    actor_is_admin = "admin" in user.role_names
    reservation = await _owned_reservation_by_identity(
        session,
        reservation_id=reservation_id,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
    )
    request_hash = _hash_payload({"reservation_id": str(reservation_id)})
    if reservation.status == RESERVATION_CONFIRMED:
        if (
            reservation.confirm_idempotency_key != idempotency_key
            or reservation.confirm_request_hash != request_hash
        ):
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Confirmation key differs")
        return reservation
    if reservation.status != RESERVATION_HELD:
        raise _error(409, "RESERVATION_NOT_CONFIRMABLE", "Reservation is not confirmable")
    now = datetime.now(UTC)
    if _aware(reservation.hold_expires_at) <= now:
        await expire_reservation_holds(session, user_id=reservation.user_id)
        await session.commit()
        raise _error(409, "RESERVATION_EXPIRED", "Reservation hold has expired")

    transitioned = await session.execute(
        update(Reservation)
        .execution_options(synchronize_session=False)
        .where(
            Reservation.id == reservation.id,
            Reservation.status == RESERVATION_HELD,
            Reservation.version == reservation.version,
            Reservation.hold_expires_at > now,
        )
        .values(
            status=RESERVATION_CONFIRMED,
            confirm_idempotency_key=idempotency_key,
            confirm_request_hash=request_hash,
            confirmed_at=now,
            version=Reservation.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        concurrent = await _owned_reservation_by_identity(
            session,
            reservation_id=reservation_id,
            actor_id=actor_id,
            actor_is_admin=actor_is_admin,
        )
        if (
            concurrent.status == RESERVATION_CONFIRMED
            and concurrent.confirm_idempotency_key == idempotency_key
        ):
            return concurrent
        raise _error(409, "RESERVATION_NOT_CONFIRMABLE", "Reservation is not confirmable")

    for allocation in sorted(reservation.allocations, key=lambda item: str(item.bucket_id)):
        confirmed = await session.execute(
            update(InventoryBucket)
            .execution_options(synchronize_session=False)
            .where(
                InventoryBucket.id == allocation.bucket_id,
                InventoryBucket.held >= allocation.quantity,
                InventoryBucket.held + InventoryBucket.confirmed <= InventoryBucket.capacity,
            )
            .values(
                held=InventoryBucket.held - allocation.quantity,
                confirmed=InventoryBucket.confirmed + allocation.quantity,
                version=InventoryBucket.version + 1,
            )
        )
        if confirmed.rowcount != 1:
            await session.rollback()
            raise _error(409, "INVENTORY_CONFLICT", "Held inventory is unavailable")
        allocation.status = RESERVATION_CONFIRMED
    await session.commit()
    loaded = await _load_reservation(session, reservation.id)
    assert loaded is not None
    return loaded


async def cancel_reservation(
    session: AsyncSession,
    *,
    reservation_id: UUID,
    user: User,
    reason: str,
    idempotency_key: str,
) -> Reservation:
    actor_id = user.id
    actor_is_admin = "admin" in user.role_names
    reservation = await _owned_reservation_by_identity(
        session,
        reservation_id=reservation_id,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
    )
    request_hash = _hash_payload({"reason": reason, "reservation_id": str(reservation_id)})
    if reservation.status == RESERVATION_CANCELLED:
        if (
            reservation.cancel_idempotency_key != idempotency_key
            or reservation.cancel_request_hash != request_hash
        ):
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Cancellation key differs")
        return reservation
    if reservation.status not in ACTIVE_RESERVATION_STATUSES:
        raise _error(409, "RESERVATION_NOT_CANCELLABLE", "Reservation is not cancellable")
    source_status = reservation.status
    transitioned = await session.execute(
        update(Reservation)
        .execution_options(synchronize_session=False)
        .where(
            Reservation.id == reservation.id,
            Reservation.status == source_status,
            Reservation.version == reservation.version,
        )
        .values(
            status=RESERVATION_CANCELLED,
            cancel_idempotency_key=idempotency_key,
            cancel_request_hash=request_hash,
            cancel_reason=reason,
            cancelled_at=datetime.now(UTC),
            version=Reservation.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        concurrent = await _owned_reservation_by_identity(
            session,
            reservation_id=reservation_id,
            actor_id=actor_id,
            actor_is_admin=actor_is_admin,
        )
        if (
            concurrent.status == RESERVATION_CANCELLED
            and concurrent.cancel_idempotency_key == idempotency_key
            and concurrent.cancel_request_hash == request_hash
        ):
            return concurrent
        raise _error(409, "RESERVATION_NOT_CANCELLABLE", "Reservation is not cancellable")
    await _release_allocations(
        session,
        reservation,
        source_status=source_status,
        target_status=RESERVATION_CANCELLED,
    )
    await session.commit()
    loaded = await _load_reservation(session, reservation.id)
    assert loaded is not None
    return loaded

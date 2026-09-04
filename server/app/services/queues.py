"""Virtual queue, FastPass quota, and suggestion-only itinerary integration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models.guide import Attraction, Itinerary, RouteNode
from app.db.models.marketplace import (
    QUEUE_CALLED,
    QUEUE_COMPLETED,
    QUEUE_LEFT,
    QUEUE_SERVING,
    QUEUE_WAITING,
    Experience,
    FastPass,
    HospitalityVenue,
    InventoryBucket,
    QueueCounter,
    QueueEntry,
)
from app.db.models.user import User
from app.providers.map import NoSchematicRouteError, SchematicMapProvider
from app.providers.payment import DemoPaymentProvider
from app.schemas.marketplace import (
    FastPassResponse,
    NearbyRecommendationResponse,
    QueueEventData,
    QueueResponse,
    QueueWebSocketEnvelope,
)
from app.services.guide import latest_crowd_by_attraction

SCENIC_TIMEZONE = ZoneInfo("Asia/Shanghai")
ACTIVE_QUEUE_STATUSES = (QUEUE_WAITING, QUEUE_CALLED, QUEUE_SERVING)


@dataclass(frozen=True, slots=True)
class QueueContext:
    entry: QueueEntry
    experience: Experience
    itinerary: Itinerary | None
    fast_pass: FastPass | None


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


def fast_pass_response(
    fast_pass: FastPass,
    experience: Experience,
) -> FastPassResponse:
    return FastPassResponse(
        id=str(fast_pass.id),
        code=fast_pass.code,
        experience_id=str(experience.id),
        experience_name=experience.name,
        price_cents=fast_pass.price_cents,
        status=fast_pass.status,
        valid_from=_aware(fast_pass.valid_from),
        valid_to=_aware(fast_pass.valid_to),
        provider=fast_pass.provider,
        is_demo=fast_pass.is_demo,
    )


async def _load_queue_context(
    session: AsyncSession,
    queue_id: UUID,
) -> QueueContext | None:
    entry = await session.get(QueueEntry, queue_id, populate_existing=True)
    if entry is None:
        return None
    experience = await session.get(Experience, entry.experience_id)
    assert experience is not None
    itinerary = (
        None
        if entry.itinerary_id is None
        else await session.get(Itinerary, entry.itinerary_id, populate_existing=True)
    )
    fast_pass = await session.scalar(
        select(FastPass)
        .execution_options(populate_existing=True)
        .where(FastPass.queue_entry_id == entry.id)
    )
    return QueueContext(entry, experience, itinerary, fast_pass)


async def _owned_queue_context(
    session: AsyncSession,
    *,
    queue_id: UUID,
    actor_id: UUID,
    actor_is_admin: bool,
) -> QueueContext:
    context = await _load_queue_context(session, queue_id)
    if context is None or (context.entry.user_id != actor_id and not actor_is_admin):
        raise _error(404, "QUEUE_NOT_FOUND", "Queue entry not found")
    return context


async def _nearby_recommendations(
    session: AsyncSession,
    *,
    experience: Experience,
    wait_minutes: int,
) -> list[NearbyRecommendationResponse]:
    _, crowds = await latest_crowd_by_attraction(session)
    attractions = list(
        await session.scalars(
            select(Attraction).where(Attraction.is_active.is_(True)).order_by(Attraction.code)
        )
    )
    nodes = list(await session.scalars(select(RouteNode)))
    nodes_by_attraction = {
        node.attraction_id: node for node in nodes if node.attraction_id is not None
    }
    candidates = sorted(
        (
            (attraction, crowds.get(attraction.id), nodes_by_attraction.get(attraction.id))
            for attraction in attractions
        ),
        key=lambda candidate: (
            {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(
                candidate[1].crowd_level if candidate[1] is not None else "HIGH",
                3,
            ),
            candidate[0].code,
        ),
    )
    provider = SchematicMapProvider()
    recommendations: list[NearbyRecommendationResponse] = []
    for attraction, crowd, node in candidates:
        if crowd is None or node is None or crowd.crowd_level == "HIGH":
            continue
        try:
            route = await provider.route(
                session,
                from_node_id=experience.node_id,
                to_node_id=node.id,
                wheelchair=False,
                stroller=False,
            )
        except NoSchematicRouteError:
            continue
        if route.walk_minutes * 2 + attraction.visit_minutes > max(wait_minutes, 10):
            continue
        recommendations.append(
            NearbyRecommendationResponse(
                kind="ATTRACTION",
                ref_id=str(attraction.id),
                name=attraction.name,
                reason=(
                    f"模拟排队约 {wait_minutes} 分钟; 该点当前为"
                    f"{crowd.crowd_level}拥挤度, 可返回队列"
                ),
                walk_minutes=route.walk_minutes,
                crowd_level=crowd.crowd_level,
            )
        )
        if len(recommendations) >= 2:
            break

    if len(recommendations) < 2:
        restaurants = list(
            await session.scalars(
                select(HospitalityVenue)
                .where(HospitalityVenue.kind == "RESTAURANT")
                .order_by(HospitalityVenue.code)
            )
        )
        for venue in restaurants:
            try:
                route = await provider.route(
                    session,
                    from_node_id=experience.node_id,
                    to_node_id=venue.node_id,
                    wheelchair=False,
                    stroller=False,
                )
            except NoSchematicRouteError:
                continue
            recommendations.append(
                NearbyRecommendationResponse(
                    kind="RESTAURANT",
                    ref_id=str(venue.id),
                    name=venue.name,
                    reason="排队期间可前往附近演示餐饮点短暂休息",
                    walk_minutes=route.walk_minutes,
                    crowd_level="LOW",
                )
            )
            if len(recommendations) >= 2:
                break
    return recommendations


async def queue_response(
    session: AsyncSession,
    context: QueueContext,
) -> QueueResponse:
    recommendations = await _nearby_recommendations(
        session,
        experience=context.experience,
        wait_minutes=context.entry.estimated_wait_minutes,
    )
    return QueueResponse(
        id=str(context.entry.id),
        queue_no=context.entry.queue_no,
        experience_id=str(context.experience.id),
        experience_name=context.experience.name,
        status=context.entry.status,
        party_size=context.entry.party_size,
        estimated_wait_minutes=context.entry.estimated_wait_minutes,
        sequence=context.entry.sequence,
        joined_at=_aware(context.entry.joined_at),
        called_at=(None if context.entry.called_at is None else _aware(context.entry.called_at)),
        itinerary_id=(None if context.itinerary is None else str(context.itinerary.id)),
        itinerary_revision=(None if context.itinerary is None else context.itinerary.revision),
        nearby_recommendations=recommendations,
        fast_pass=(
            None
            if context.fast_pass is None
            else fast_pass_response(context.fast_pass, context.experience)
        ),
    )


def queue_envelope(
    response: QueueResponse,
    *,
    event_type: str = "queue.updated",
) -> QueueWebSocketEnvelope:
    # 创新点 4: 队列事件只携带生成建议时看到的行程版本, 不直接改写行程;
    # 客户端应用建议前必须核对 itinerary_revision, 从而拒绝覆盖新行程的旧建议。
    recommendation = response.nearby_recommendations[0] if response.nearby_recommendations else None
    selected_type = event_type
    if event_type == "queue.updated" and response.itinerary_id and recommendation:
        selected_type = "itinerary.replan_available"
    elif event_type == "queue.updated" and recommendation and response.status == QUEUE_WAITING:
        selected_type = "nearby.recommended"
    return QueueWebSocketEnvelope(
        id=str(uuid4()),
        type=selected_type,
        occurred_at=datetime.now(UTC),
        data=QueueEventData(
            queue=response,
            source="simulated",
            is_demo=True,
            recommendation=recommendation,
            itinerary_id=response.itinerary_id,
            itinerary_revision=response.itinerary_revision,
        ),
    )


async def _next_join_sequence(
    session: AsyncSession,
    experience_id: UUID,
) -> int:
    values = {"experience_id": experience_id, "next_sequence": 1}
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        await session.execute(sqlite_insert(QueueCounter).values(**values).on_conflict_do_nothing())
    elif bind.dialect.name == "postgresql":
        await session.execute(
            postgresql_insert(QueueCounter)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[QueueCounter.experience_id])
        )
    elif await session.get(QueueCounter, experience_id) is None:
        session.add(QueueCounter(**values))
        await session.flush()
    result = await session.execute(
        update(QueueCounter)
        .execution_options(synchronize_session=False)
        .where(QueueCounter.experience_id == experience_id)
        .values(next_sequence=QueueCounter.next_sequence + 1)
        .returning(QueueCounter.next_sequence)
    )
    next_sequence = result.scalar_one()
    return next_sequence - 1


async def join_queue(
    session: AsyncSession,
    *,
    user: User,
    experience_id: UUID,
    party_size: int,
    itinerary_id: UUID | None,
    idempotency_key: str,
) -> QueueContext:
    actor_id = user.id
    request_hash = _hash_payload(
        {
            "experience_id": str(experience_id),
            "itinerary_id": None if itinerary_id is None else str(itinerary_id),
            "party_size": party_size,
        }
    )
    existing = await session.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == actor_id,
            QueueEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Queue key payload differs")
        context = await _load_queue_context(session, existing.id)
        assert context is not None
        return context

    experience = await session.get(Experience, experience_id)
    if experience is None or not experience.is_active:
        raise _error(404, "EXPERIENCE_NOT_FOUND", "Experience not found")
    itinerary = None
    if itinerary_id is not None:
        itinerary = await session.get(Itinerary, itinerary_id)
        if itinerary is None or itinerary.user_id != actor_id:
            raise _error(404, "ITINERARY_NOT_FOUND", "Itinerary not found")

    join_sequence = await _next_join_sequence(session, experience_id)
    existing = await session.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == actor_id,
            QueueEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            await session.rollback()
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Queue key payload differs")
        await session.rollback()
        context = await _load_queue_context(session, existing.id)
        assert context is not None
        return context
    active = await session.scalar(
        select(QueueEntry).where(
            QueueEntry.user_id == actor_id,
            QueueEntry.experience_id == experience_id,
            QueueEntry.active_key == "ACTIVE",
        )
    )
    if active is not None:
        await session.rollback()
        raise _error(409, "QUEUE_ALREADY_ACTIVE", "An active queue entry already exists")
    ahead = int(
        await session.scalar(
            select(func.count())
            .select_from(QueueEntry)
            .where(
                QueueEntry.experience_id == experience_id,
                QueueEntry.status.in_(ACTIVE_QUEUE_STATUSES),
            )
        )
        or 0
    )
    entry_id = uuid4()
    entry = QueueEntry(
        id=entry_id,
        queue_no=(
            f"Q-{datetime.now(UTC):%Y%m%d}-{experience.code[:10].upper()}-{join_sequence:05d}"
        ),
        user_id=actor_id,
        experience_id=experience_id,
        itinerary_id=None if itinerary is None else itinerary.id,
        status=QUEUE_WAITING,
        active_key="ACTIVE",
        party_size=party_size,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        estimated_wait_minutes=max(experience.wait_minutes, ahead * experience.duration_minutes),
        sequence=1,
        join_sequence=join_sequence,
    )
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(QueueEntry).where(
                QueueEntry.user_id == actor_id,
                QueueEntry.idempotency_key == idempotency_key,
            )
        )
        if concurrent is not None and concurrent.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Queue key payload differs") from exc
        if concurrent is not None:
            entry_id = concurrent.id
        else:
            active = await session.scalar(
                select(QueueEntry).where(
                    QueueEntry.user_id == actor_id,
                    QueueEntry.experience_id == experience_id,
                    QueueEntry.active_key == "ACTIVE",
                )
            )
            if active is not None:
                raise _error(
                    409,
                    "QUEUE_ALREADY_ACTIVE",
                    "An active queue entry already exists",
                ) from exc
            raise _error(409, "QUEUE_CONFLICT", "Queue entry could not be created") from exc
    context = await _load_queue_context(session, entry_id)
    assert context is not None
    return context


async def get_queue(
    session: AsyncSession,
    *,
    queue_id: UUID,
    user: User,
) -> QueueContext:
    return await _owned_queue_context(
        session,
        queue_id=queue_id,
        actor_id=user.id,
        actor_is_admin="admin" in user.role_names,
    )


async def get_queue_by_identity(
    session: AsyncSession,
    *,
    queue_id: UUID,
    actor_id: UUID,
) -> QueueContext:
    return await _owned_queue_context(
        session,
        queue_id=queue_id,
        actor_id=actor_id,
        actor_is_admin=False,
    )


async def leave_queue(
    session: AsyncSession,
    *,
    queue_id: UUID,
    user: User,
    idempotency_key: str,
) -> QueueContext:
    actor_id = user.id
    actor_is_admin = "admin" in user.role_names
    context = await _owned_queue_context(
        session,
        queue_id=queue_id,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
    )
    request_hash = _hash_payload({"queue_id": str(queue_id)})
    if context.entry.status == QUEUE_LEFT:
        if (
            context.entry.leave_idempotency_key != idempotency_key
            or context.entry.leave_request_hash != request_hash
        ):
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Queue leave key differs")
        return context
    if context.entry.status not in ACTIVE_QUEUE_STATUSES:
        raise _error(409, "QUEUE_NOT_LEAVABLE", "Queue entry is not active")
    transitioned = await session.execute(
        update(QueueEntry)
        .execution_options(synchronize_session=False)
        .where(
            QueueEntry.id == queue_id,
            QueueEntry.status == context.entry.status,
            QueueEntry.version == context.entry.version,
        )
        .values(
            status=QUEUE_LEFT,
            active_key=None,
            leave_idempotency_key=idempotency_key,
            leave_request_hash=request_hash,
            left_at=datetime.now(UTC),
            sequence=QueueEntry.sequence + 1,
            version=QueueEntry.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        concurrent = await _owned_queue_context(
            session,
            queue_id=queue_id,
            actor_id=actor_id,
            actor_is_admin=actor_is_admin,
        )
        if (
            concurrent.entry.status == QUEUE_LEFT
            and concurrent.entry.leave_idempotency_key == idempotency_key
        ):
            return concurrent
        raise _error(409, "QUEUE_NOT_LEAVABLE", "Queue entry is not active")

    if context.fast_pass is not None and context.fast_pass.status == "ACTIVE":
        cancelled = await session.execute(
            update(FastPass)
            .execution_options(synchronize_session=False)
            .where(FastPass.id == context.fast_pass.id, FastPass.status == "ACTIVE")
            .values(status="CANCELLED")
        )
        released = await session.execute(
            update(InventoryBucket)
            .execution_options(synchronize_session=False)
            .where(
                InventoryBucket.id == context.fast_pass.bucket_id,
                InventoryBucket.confirmed >= 1,
            )
            .values(
                confirmed=InventoryBucket.confirmed - 1,
                version=InventoryBucket.version + 1,
            )
        )
        if cancelled.rowcount != 1 or released.rowcount != 1:
            await session.rollback()
            raise _error(409, "FAST_PASS_CONFLICT", "FastPass quota ledger is inconsistent")
    await session.commit()
    loaded = await _load_queue_context(session, queue_id)
    assert loaded is not None
    return loaded


async def buy_fast_pass(
    session: AsyncSession,
    *,
    queue_id: UUID,
    user: User,
    idempotency_key: str,
    settings: Settings,
    payment_provider: DemoPaymentProvider | None = None,
) -> QueueContext:
    actor_id = user.id
    actor_is_admin = "admin" in user.role_names
    context = await _owned_queue_context(
        session,
        queue_id=queue_id,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
    )
    if context.entry.user_id != actor_id:
        raise _error(403, "FORBIDDEN", "FastPass can only be bought by the queue owner")
    existing_by_key = await session.scalar(
        select(FastPass).where(
            FastPass.user_id == actor_id,
            FastPass.idempotency_key == idempotency_key,
        )
    )
    if existing_by_key is not None:
        if existing_by_key.queue_entry_id != queue_id:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "FastPass key payload differs")
        loaded = await _load_queue_context(session, queue_id)
        assert loaded is not None
        return loaded
    if context.fast_pass is not None:
        raise _error(409, "FAST_PASS_ALREADY_EXISTS", "Queue already has a FastPass")
    if context.entry.status not in {QUEUE_WAITING, QUEUE_CALLED}:
        raise _error(409, "FAST_PASS_NOT_AVAILABLE", "Queue is not eligible for FastPass")
    if not context.experience.fastpass_allowed:
        raise _error(409, "FAST_PASS_NOT_AVAILABLE", "Experience does not offer FastPass")

    claimed = await session.execute(
        update(QueueEntry)
        .execution_options(synchronize_session=False)
        .where(
            QueueEntry.id == queue_id,
            QueueEntry.status.in_((QUEUE_WAITING, QUEUE_CALLED)),
            QueueEntry.version == context.entry.version,
        )
        .values(version=QueueEntry.version + 1)
    )
    if claimed.rowcount != 1:
        await session.rollback()
        raise _error(409, "FAST_PASS_NOT_AVAILABLE", "Queue state changed")

    scenic_today = datetime.now(SCENIC_TIMEZONE).date()
    bucket = await session.scalar(
        select(InventoryBucket).where(
            InventoryBucket.resource_type == "FAST_PASS",
            InventoryBucket.resource_id == context.experience.id,
            InventoryBucket.business_date == scenic_today,
        )
    )
    if bucket is None:
        raise _error(409, "FAST_PASS_NOT_AVAILABLE", "FastPass quota is unavailable")
    reserved = await session.execute(
        update(InventoryBucket)
        .execution_options(synchronize_session=False)
        .where(
            InventoryBucket.id == bucket.id,
            InventoryBucket.held + InventoryBucket.confirmed + 1 <= InventoryBucket.capacity,
        )
        .values(
            confirmed=InventoryBucket.confirmed + 1,
            version=InventoryBucket.version + 1,
        )
    )
    if reserved.rowcount != 1:
        await session.rollback()
        raise _error(409, "FAST_PASS_SOLD_OUT", "FastPass quota is sold out")
    provider = payment_provider or DemoPaymentProvider()
    try:
        payment = await provider.authorize(
            order_no=context.entry.queue_no,
            amount_cents=context.experience.fastpass_price_cents,
            idempotency_key=idempotency_key,
        )
    except Exception:
        await session.rollback()
        raise
    now = datetime.now(UTC)
    valid_from = max(now, _aware(bucket.starts_at))
    valid_to = min(
        _aware(bucket.ends_at),
        now + timedelta(minutes=settings.fastpass_valid_minutes),
    )
    if valid_to <= valid_from:
        await session.rollback()
        raise _error(409, "FAST_PASS_NOT_AVAILABLE", "FastPass quota window has closed")
    fast_pass = FastPass(
        code=f"FP-{uuid4().hex[:16].upper()}",
        queue_entry_id=queue_id,
        user_id=actor_id,
        experience_id=context.experience.id,
        bucket_id=bucket.id,
        price_cents=context.experience.fastpass_price_cents,
        status="ACTIVE",
        valid_from=valid_from,
        valid_to=valid_to,
        provider="demo",
        is_demo=True,
        idempotency_key=idempotency_key,
        payment_reference=payment.reference,
    )
    session.add(fast_pass)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(FastPass).where(FastPass.queue_entry_id == queue_id)
        )
        if concurrent is None or concurrent.idempotency_key != idempotency_key:
            raise _error(
                409,
                "FAST_PASS_ALREADY_EXISTS",
                "Queue already has a FastPass",
            ) from exc
    loaded = await _load_queue_context(session, queue_id)
    assert loaded is not None
    return loaded


async def advance_queue_tick(
    session: AsyncSession,
) -> list[QueueResponse]:
    """Advance each demo queue by one deterministic service cycle."""

    now = datetime.now(UTC)
    await session.execute(
        update(FastPass)
        .execution_options(synchronize_session=False)
        .where(FastPass.status == "ACTIVE", FastPass.valid_to <= now)
        .values(status="EXPIRED")
    )
    entries = list(
        await session.scalars(
            select(QueueEntry)
            .where(QueueEntry.status.in_(ACTIVE_QUEUE_STATUSES))
            .order_by(QueueEntry.experience_id, QueueEntry.join_sequence)
        )
    )
    experience_ids = sorted({entry.experience_id for entry in entries}, key=str)
    fast_pass_queue_ids = set(
        await session.scalars(
            select(FastPass.queue_entry_id).where(
                FastPass.status == "ACTIVE",
                FastPass.valid_from <= now,
                FastPass.valid_to > now,
            )
        )
    )
    changed_ids: set[UUID] = set()
    for experience_id in experience_ids:
        group = [entry for entry in entries if entry.experience_id == experience_id]
        serving = [entry for entry in group if entry.status == QUEUE_SERVING]
        called = [entry for entry in group if entry.status == QUEUE_CALLED]
        waiting = [entry for entry in group if entry.status == QUEUE_WAITING]
        waiting.sort(
            key=lambda entry: (
                0 if entry.id in fast_pass_queue_ids else 1,
                entry.join_sequence,
            )
        )

        if serving:
            current = serving[0]
            result = await session.execute(
                update(QueueEntry)
                .execution_options(synchronize_session=False)
                .where(
                    QueueEntry.id == current.id,
                    QueueEntry.status == QUEUE_SERVING,
                    QueueEntry.version == current.version,
                )
                .values(
                    status=QUEUE_COMPLETED,
                    active_key=None,
                    sequence=QueueEntry.sequence + 1,
                    version=QueueEntry.version + 1,
                )
            )
            if result.rowcount == 1:
                changed_ids.add(current.id)

        if called:
            current = called[0]
            result = await session.execute(
                update(QueueEntry)
                .execution_options(synchronize_session=False)
                .where(
                    QueueEntry.id == current.id,
                    QueueEntry.status == QUEUE_CALLED,
                    QueueEntry.version == current.version,
                )
                .values(
                    status=QUEUE_SERVING,
                    serving_at=now,
                    estimated_wait_minutes=0,
                    sequence=QueueEntry.sequence + 1,
                    version=QueueEntry.version + 1,
                )
            )
            if result.rowcount == 1:
                changed_ids.add(current.id)
                await session.execute(
                    update(FastPass)
                    .execution_options(synchronize_session=False)
                    .where(
                        FastPass.queue_entry_id == current.id,
                        FastPass.status == "ACTIVE",
                    )
                    .values(status="USED")
                )

        if waiting:
            current = waiting.pop(0)
            result = await session.execute(
                update(QueueEntry)
                .execution_options(synchronize_session=False)
                .where(
                    QueueEntry.id == current.id,
                    QueueEntry.status == QUEUE_WAITING,
                    QueueEntry.version == current.version,
                )
                .values(
                    status=QUEUE_CALLED,
                    called_at=now,
                    estimated_wait_minutes=0,
                    sequence=QueueEntry.sequence + 1,
                    version=QueueEntry.version + 1,
                )
            )
            if result.rowcount == 1:
                changed_ids.add(current.id)

        experience = await session.get(Experience, experience_id)
        assert experience is not None
        for position, entry in enumerate(waiting, start=1):
            estimate = max(position * experience.duration_minutes, 1)
            if entry.estimated_wait_minutes == estimate:
                continue
            result = await session.execute(
                update(QueueEntry)
                .execution_options(synchronize_session=False)
                .where(
                    QueueEntry.id == entry.id,
                    QueueEntry.status == QUEUE_WAITING,
                    QueueEntry.version == entry.version,
                )
                .values(
                    estimated_wait_minutes=estimate,
                    sequence=QueueEntry.sequence + 1,
                    version=QueueEntry.version + 1,
                )
            )
            if result.rowcount == 1:
                changed_ids.add(entry.id)
    await session.commit()
    responses: list[QueueResponse] = []
    for queue_id in sorted(changed_ids, key=str):
        context = await _load_queue_context(session, queue_id)
        if context is not None:
            responses.append(await queue_response(session, context))
    return responses

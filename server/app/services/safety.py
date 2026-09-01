"""Curated emergency information and explicit demo-only SOS lifecycle."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models.guide import RouteNode
from app.db.models.journey import (
    EmergencyBulletin,
    EmergencyResource,
    SosRequest,
)
from app.db.models.user import User
from app.providers.journey import DemoEmergencyProvider
from app.schemas.journey import (
    EmergencyBulletinResponse,
    EmergencyResourceResponse,
    SosResponse,
)


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()


def _is_staff(user: User) -> bool:
    return bool({"support", "admin"}.intersection(user.role_names))


async def list_emergency_resources(
    session: AsyncSession,
) -> list[EmergencyResourceResponse]:
    resources = list(
        await session.scalars(
            select(EmergencyResource)
            .where(EmergencyResource.is_active.is_(True))
            .order_by(EmergencyResource.priority, EmergencyResource.code)
        )
    )
    return [
        EmergencyResourceResponse(
            id=str(resource.id),
            code=resource.code,
            kind=resource.kind,
            title=resource.title,
            description=resource.description,
            phone=resource.phone,
            node_id=None if resource.node_id is None else str(resource.node_id),
            instructions=resource.instructions,
            priority=resource.priority,
            provider="curated_demo",
            is_demo=resource.is_demo,
        )
        for resource in resources
    ]


async def list_emergency_bulletins(
    session: AsyncSession,
) -> list[EmergencyBulletinResponse]:
    now = datetime.now(UTC)
    bulletins = list(
        await session.scalars(
            select(EmergencyBulletin).where(EmergencyBulletin.is_active.is_(True))
        )
    )
    active = [
        bulletin
        for bulletin in bulletins
        if _aware(bulletin.starts_at) <= now < _aware(bulletin.ends_at)
    ]
    active.sort(key=lambda item: (item.severity != "CRITICAL", item.code))
    return [
        EmergencyBulletinResponse(
            id=str(bulletin.id),
            code=bulletin.code,
            title=bulletin.title,
            content=bulletin.content,
            severity=bulletin.severity,
            starts_at=_aware(bulletin.starts_at),
            ends_at=_aware(bulletin.ends_at),
            provider="curated_demo",
            is_demo=bulletin.is_demo,
        )
        for bulletin in active
    ]


def sos_response(sos: SosRequest) -> SosResponse:
    return SosResponse(
        id=str(sos.id),
        sos_no=sos.sos_no,
        kind=sos.kind,
        message=sos.message,
        status=sos.status,
        node_id=None if sos.node_id is None else str(sos.node_id),
        latitude=(None if sos.latitude_e6 is None else sos.latitude_e6 / 1_000_000),
        longitude=(None if sos.longitude_e6 is None else sos.longitude_e6 / 1_000_000),
        provider="demo_sos",
        is_demo=True,
        real_dispatch=False,
        disclaimer="演示 SOS 仅持久化请求, 未联系真实急救或公共安全机构",
        created_at=_aware(sos.created_at),
        updated_at=_aware(sos.updated_at),
    )


async def create_sos(
    session: AsyncSession,
    *,
    user: User,
    kind: str,
    message: str,
    node_id: UUID | None,
    latitude: float | None,
    longitude: float | None,
    idempotency_key: str,
    provider: DemoEmergencyProvider | None = None,
) -> SosRequest:
    actor_id = user.id
    normalized_message = message.strip()
    if len(normalized_message) < 2:
        raise _error(422, "SOS_MESSAGE_INVALID", "SOS message is blank")
    if (latitude is None) != (longitude is None):
        raise _error(
            422,
            "SOS_COORDINATES_INVALID",
            "Latitude and longitude must be provided together",
        )
    request_payload = {
        "kind": kind,
        "latitude": latitude,
        "longitude": longitude,
        "message": normalized_message,
        "node_id": None if node_id is None else str(node_id),
    }
    request_hash = _hash_payload(request_payload)
    existing = await session.scalar(
        select(SosRequest).where(
            SosRequest.user_id == actor_id,
            SosRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "SOS key payload differs")
        return existing
    if node_id is not None and await session.get(RouteNode, node_id) is None:
        raise _error(404, "ROUTE_NODE_NOT_FOUND", "Route node not found")
    dispatcher = provider or DemoEmergencyProvider()
    dispatched = await dispatcher.submit(
        user_id=str(actor_id),
        kind=kind,
        message=normalized_message,
        idempotency_key=idempotency_key,
    )
    if dispatched.dispatched_real_services:
        raise RuntimeError("Demo provider must never dispatch real services")
    sos_id = uuid4()
    sos = SosRequest(
        id=sos_id,
        sos_no=f"SOS-DEMO-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}",
        user_id=actor_id,
        kind=kind,
        message=normalized_message,
        status=dispatched.status,
        node_id=node_id,
        latitude_e6=None if latitude is None else round(latitude * 1_000_000),
        longitude_e6=(None if longitude is None else round(longitude * 1_000_000)),
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        provider=dispatched.provider,
        is_demo=dispatched.is_demo,
    )
    session.add(sos)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(
            select(SosRequest).where(
                SosRequest.user_id == actor_id,
                SosRequest.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None or concurrent.request_hash != request_hash:
            raise _error(409, "SOS_CONFLICT", "SOS request could not be recorded") from exc
        sos_id = concurrent.id
    loaded = await session.get(SosRequest, sos_id, populate_existing=True)
    assert loaded is not None
    return loaded


async def _visible_sos(
    session: AsyncSession,
    *,
    sos_id: UUID,
    user: User,
) -> SosRequest:
    sos = await session.get(SosRequest, sos_id, populate_existing=True)
    if sos is None or (sos.user_id != user.id and not _is_staff(user)):
        raise _error(404, "SOS_NOT_FOUND", "SOS request not found")
    return sos


async def list_sos(session: AsyncSession, *, user: User) -> list[SosRequest]:
    statement = select(SosRequest).order_by(SosRequest.created_at.desc())
    if not _is_staff(user):
        statement = statement.where(SosRequest.user_id == user.id)
    return list(await session.scalars(statement))


async def get_sos(
    session: AsyncSession,
    *,
    sos_id: UUID,
    user: User,
) -> SosRequest:
    return await _visible_sos(session, sos_id=sos_id, user=user)


async def transition_sos(
    session: AsyncSession,
    *,
    sos_id: UUID,
    actor: User,
    target_status: str,
) -> SosRequest:
    if not _is_staff(actor):
        raise _error(403, "FORBIDDEN", "Support role required")
    sos = await _visible_sos(session, sos_id=sos_id, user=actor)
    allowed = {
        ("DEMO_RECEIVED", "ACKNOWLEDGED"),
        ("ACKNOWLEDGED", "RESOLVED"),
    }
    if (sos.status, target_status) not in allowed:
        raise _error(409, "SOS_STATE_INVALID", "SOS transition is not allowed")
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "status": target_status,
        "updated_at": now,
        "version": SosRequest.version + 1,
    }
    if target_status == "ACKNOWLEDGED":
        values["acknowledged_at"] = now
    else:
        values["resolved_at"] = now
    transitioned = await session.execute(
        update(SosRequest)
        .execution_options(synchronize_session=False)
        .where(
            SosRequest.id == sos.id,
            SosRequest.status == sos.status,
            SosRequest.version == sos.version,
        )
        .values(**values)
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "SOS_CONFLICT", "SOS request changed concurrently")
    await session.commit()
    loaded = await session.get(SosRequest, sos.id, populate_existing=True)
    assert loaded is not None
    return loaded

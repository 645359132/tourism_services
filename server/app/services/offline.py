"""Offline pack delivery and user-bound opaque cursor synchronization."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models.guide import Itinerary
from app.db.models.journey import (
    DeviceSyncState,
    EmergencyBulletin,
    OfflineMutation,
    OfflinePack,
    UserSyncCounter,
)
from app.db.models.user import User
from app.schemas.journey import (
    OfflineAssetContentResponse,
    OfflineAssetManifestResponse,
    OfflineManifestResponse,
    OfflineMutationRequest,
    OfflinePackResponse,
    SyncMutationResponse,
    SyncPullResponse,
    SyncPushResponse,
    SyncPushResult,
    SyncStatusResponse,
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


def encode_cursor(
    *,
    user_id: UUID,
    device_id: str,
    cursor: int,
    settings: Settings,
) -> str:
    # 创新点 7: 同步游标不仅是分页数字, 还签名绑定用户、设备和协议版本;
    # 因此游标不可篡改, 也不能跨账号或跨设备复用。
    payload = json.dumps(
        {
            "cursor": cursor,
            "device_id": device_id,
            "epoch": 1,
            "user_id": str(user_id),
            "version": 2,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = (
        hmac.new(
            settings.jwt_secret_key.encode(),
            payload,
            sha256,
        )
        .hexdigest()
        .encode()
    )
    return base64.urlsafe_b64encode(payload + b"." + signature).decode().rstrip("=")


def decode_cursor(
    token: str | None,
    *,
    user_id: UUID,
    device_id: str,
    settings: Settings,
) -> int:
    if token is None:
        return 0
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode())
        payload, signature = decoded.rsplit(b".", 1)
        expected = (
            hmac.new(
                settings.jwt_secret_key.encode(),
                payload,
                sha256,
            )
            .hexdigest()
            .encode()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        data = json.loads(payload.decode())
        if (
            not isinstance(data, dict)
            or data.get("version") != 2
            or data.get("epoch") != 1
            or UUID(str(data.get("user_id"))) != user_id
            or data.get("device_id") != device_id
        ):
            raise ValueError
        cursor = int(data["cursor"])
        if cursor < 0:
            raise ValueError
        return cursor
    except (
        ValueError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise _error(
            409,
            "SYNC_CURSOR_INVALID",
            "Sync cursor is invalid or belongs to another user; perform full resync",
        ) from exc


def _pack_statement():
    return select(OfflinePack).options(selectinload(OfflinePack.assets))


async def latest_pack(session: AsyncSession) -> OfflinePack:
    pack = await session.scalar(
        _pack_statement()
        .where(OfflinePack.is_active.is_(True))
        .order_by(OfflinePack.version.desc())
        .limit(1)
    )
    if pack is None:
        raise _error(404, "OFFLINE_PACK_NOT_FOUND", "Offline pack not found")
    return pack


async def get_pack(session: AsyncSession, pack_id: UUID) -> OfflinePack:
    pack = await session.scalar(
        _pack_statement().where(
            OfflinePack.id == pack_id,
            OfflinePack.is_active.is_(True),
        )
    )
    if pack is None:
        raise _error(404, "OFFLINE_PACK_NOT_FOUND", "Offline pack not found")
    return pack


def pack_response(pack: OfflinePack) -> OfflinePackResponse:
    return OfflinePackResponse(
        id=str(pack.id),
        version=pack.version,
        name=pack.name,
        description=pack.description,
        etag=f'"{pack.etag}"',
        published_at=_aware(pack.published_at),
        expires_at=None if pack.expires_at is None else _aware(pack.expires_at),
        asset_count=len(pack.assets),
        total_size_bytes=sum(asset.size_bytes for asset in pack.assets),
        manifest_url=f"/api/v1/offline/packs/{pack.id}/manifest",
        provider="local_offline_pack",
        is_demo=pack.is_demo,
    )


def manifest_response(pack: OfflinePack) -> OfflineManifestResponse:
    return OfflineManifestResponse(
        pack_id=str(pack.id),
        version=pack.version,
        etag=f'"{pack.etag}"',
        assets=[
            OfflineAssetManifestResponse(
                id=str(asset.id),
                asset_key=asset.asset_key,
                kind=asset.kind,
                title=asset.title,
                content_hash=asset.content_hash,
                encoding="json",
                size_bytes=asset.size_bytes,
                required=asset.required,
                download_url=(f"/api/v1/offline/packs/{pack.id}/assets/{asset.id}"),
            )
            for asset in pack.assets
        ],
        provider="local_offline_pack",
        is_demo=pack.is_demo,
    )


async def asset_content(
    session: AsyncSession,
    *,
    pack_id: UUID,
    asset_id: UUID,
) -> OfflineAssetContentResponse:
    pack = await get_pack(session, pack_id)
    asset = next((item for item in pack.assets if item.id == asset_id), None)
    if asset is None:
        raise _error(404, "OFFLINE_ASSET_NOT_FOUND", "Offline asset not found")
    return OfflineAssetContentResponse(
        id=str(asset.id),
        pack_id=str(pack.id),
        asset_key=asset.asset_key,
        kind=asset.kind,
        content_hash=asset.content_hash,
        encoding="json",
        size_bytes=asset.size_bytes,
        payload=asset.payload,
    )


async def _ensure_sync_state(
    session: AsyncSession,
    *,
    user_id: UUID,
    device_id: str,
) -> DeviceSyncState:
    bind = session.get_bind()
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "device_id": device_id,
        "cursor": 0,
        "last_client_version": 0,
        "version": 1,
    }
    if bind.dialect.name == "sqlite":
        await session.execute(
            sqlite_insert(DeviceSyncState).values(**values).on_conflict_do_nothing()
        )
        await session.execute(
            sqlite_insert(UserSyncCounter)
            .values(user_id=user_id, next_cursor=1)
            .on_conflict_do_nothing()
        )
    elif bind.dialect.name == "postgresql":
        await session.execute(
            postgresql_insert(DeviceSyncState)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[DeviceSyncState.user_id, DeviceSyncState.device_id]
            )
        )
        await session.execute(
            postgresql_insert(UserSyncCounter)
            .values(user_id=user_id, next_cursor=1)
            .on_conflict_do_nothing(index_elements=[UserSyncCounter.user_id])
        )
    else:
        state = await session.scalar(
            select(DeviceSyncState).where(
                DeviceSyncState.user_id == user_id,
                DeviceSyncState.device_id == device_id,
            )
        )
        if state is None:
            session.add(DeviceSyncState(**values))
        if await session.get(UserSyncCounter, user_id) is None:
            session.add(UserSyncCounter(user_id=user_id, next_cursor=1))
        await session.flush()
    state = await session.scalar(
        select(DeviceSyncState)
        .execution_options(populate_existing=True)
        .where(
            DeviceSyncState.user_id == user_id,
            DeviceSyncState.device_id == device_id,
        )
    )
    assert state is not None
    return state


async def _server_cursor(session: AsyncSession, user_id: UUID) -> int:
    counter = await session.get(UserSyncCounter, user_id)
    return 0 if counter is None else counter.next_cursor - 1


def _validate_mutation(mutation: OfflineMutationRequest) -> None:
    # 创新点 7: 离线 outbox 采用显式白名单, 仅允许便签和“已读/已查看”类低风险操作;
    # 预约、支付、SOS、护照打卡等需要在线核验的动作不会通过通用同步通道执行。
    payload = mutation.payload
    if mutation.operation == "DELETE":
        if mutation.entity_type != "NOTE":
            raise _error(
                422,
                "SYNC_DELETE_NOT_ALLOWED",
                "Only offline notes may be deleted",
            )
        if payload:
            raise _error(422, "SYNC_PAYLOAD_INVALID", "DELETE payload must be empty")
        return
    if mutation.entity_type == "NOTE":
        if set(payload) - {"text", "title"}:
            raise _error(422, "SYNC_PAYLOAD_INVALID", "NOTE payload contains unknown fields")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise _error(422, "SYNC_PAYLOAD_INVALID", "NOTE text is invalid")
    elif mutation.entity_type == "ITINERARY_ACK":
        if set(payload) - {"revision", "viewed_at"}:
            raise _error(
                422,
                "SYNC_PAYLOAD_INVALID",
                "ITINERARY_ACK payload contains unknown fields",
            )
        revision = payload.get("revision")
        if not isinstance(revision, int) or revision < 1:
            raise _error(
                422,
                "SYNC_TARGET_REVISION_INVALID",
                "Itinerary revision is invalid",
            )
    elif mutation.entity_type == "EMERGENCY_ACK":
        if set(payload) - {"acknowledged", "bulletin_id"}:
            raise _error(
                422,
                "SYNC_PAYLOAD_INVALID",
                "EMERGENCY_ACK payload contains unknown fields",
            )
        if payload.get("acknowledged") is not True:
            raise _error(422, "SYNC_PAYLOAD_INVALID", "Emergency ACK must be true")
        try:
            UUID(str(payload.get("bulletin_id")))
        except ValueError as exc:
            raise _error(
                422,
                "SYNC_PAYLOAD_INVALID",
                "Emergency bulletin ID is invalid",
            ) from exc


async def _validate_mutation_target(
    session: AsyncSession,
    *,
    user_id: UUID,
    mutation: OfflineMutationRequest,
) -> None:
    if mutation.entity_type == "NOTE":
        return
    if mutation.entity_type == "ITINERARY_ACK":
        try:
            itinerary_id = UUID(mutation.entity_id)
        except ValueError as exc:
            raise _error(
                404,
                "SYNC_TARGET_NOT_FOUND",
                "Itinerary target was not found",
            ) from exc
        itinerary = await session.scalar(
            select(Itinerary).where(
                Itinerary.id == itinerary_id,
                Itinerary.user_id == user_id,
            )
        )
        if itinerary is None:
            raise _error(
                404,
                "SYNC_TARGET_NOT_FOUND",
                "Itinerary target was not found",
            )
        revision = mutation.payload.get("revision")
        assert isinstance(revision, int)
        if revision < itinerary.revision:
            raise _error(
                409,
                "SYNC_TARGET_STALE",
                "Itinerary acknowledgement revision is stale",
            )
        if revision > itinerary.revision:
            raise _error(
                409,
                "SYNC_TARGET_REVISION_INVALID",
                "Itinerary acknowledgement revision is ahead of the current revision",
            )
        return
    if mutation.entity_type == "EMERGENCY_ACK":
        try:
            entity_id = UUID(mutation.entity_id)
            bulletin_id = UUID(str(mutation.payload.get("bulletin_id")))
        except ValueError as exc:
            raise _error(
                404,
                "SYNC_TARGET_NOT_FOUND",
                "Emergency bulletin target was not found",
            ) from exc
        if entity_id != bulletin_id:
            raise _error(
                422,
                "SYNC_TARGET_MISMATCH",
                "Emergency acknowledgement target does not match its payload",
            )
        bulletin = await session.get(EmergencyBulletin, bulletin_id)
        if bulletin is None:
            raise _error(
                404,
                "SYNC_TARGET_NOT_FOUND",
                "Emergency bulletin target was not found",
            )
        now = datetime.now(UTC)
        if (
            not bulletin.is_active
            or now < _aware(bulletin.starts_at)
            or now >= _aware(bulletin.ends_at)
        ):
            raise _error(
                409,
                "SYNC_TARGET_INACTIVE",
                "Emergency bulletin is not currently active",
            )


async def sync_status(
    session: AsyncSession,
    *,
    user: User,
    device_id: str,
    settings: Settings,
) -> SyncStatusResponse:
    state = await _ensure_sync_state(
        session,
        user_id=user.id,
        device_id=device_id,
    )
    current = await _server_cursor(session, user.id)
    response = SyncStatusResponse(
        device_id=device_id,
        cursor=encode_cursor(
            user_id=user.id,
            device_id=device_id,
            cursor=state.cursor,
            settings=settings,
        ),
        last_client_version=state.last_client_version,
        server_cursor=encode_cursor(
            user_id=user.id,
            device_id=device_id,
            cursor=current,
            settings=settings,
        ),
        updated_at=_aware(state.updated_at),
    )
    await session.commit()
    return response


async def push_mutations(
    session: AsyncSession,
    *,
    user: User,
    device_id: str,
    base_cursor: str | None,
    mutations: list[OfflineMutationRequest],
    settings: Settings,
) -> SyncPushResponse:
    actor_id = user.id
    decoded_base = decode_cursor(
        base_cursor,
        user_id=actor_id,
        device_id=device_id,
        settings=settings,
    )
    state = await _ensure_sync_state(
        session,
        user_id=actor_id,
        device_id=device_id,
    )
    locked = await session.execute(
        update(DeviceSyncState)
        .execution_options(synchronize_session=False)
        .where(
            DeviceSyncState.id == state.id,
            DeviceSyncState.version == state.version,
        )
        .values(version=DeviceSyncState.version + 1)
    )
    if locked.rowcount != 1:
        await session.rollback()
        raise _error(409, "SYNC_CONFLICT", "Device sync state changed")
    current_server_cursor = await _server_cursor(session, actor_id)
    if decoded_base > current_server_cursor:
        await session.rollback()
        raise _error(
            409,
            "SYNC_CURSOR_AHEAD",
            "Cursor is ahead of server state; perform full resync",
        )
    state = await session.scalar(
        select(DeviceSyncState)
        .execution_options(populate_existing=True)
        .where(DeviceSyncState.id == state.id)
    )
    assert state is not None
    results: list[SyncPushResult] = []
    accepted = 0
    replayed = 0
    last_version = state.last_client_version
    # 创新点 7: mutation ID + 请求摘要保证重试可重放, 单调 client_version 防止乱序旧写覆盖新状态。
    for mutation in mutations:
        _validate_mutation(mutation)
        request_hash = _hash_payload(mutation.model_dump(mode="json"))
        existing = await session.scalar(
            select(OfflineMutation).where(
                OfflineMutation.user_id == actor_id,
                OfflineMutation.device_id == device_id,
                OfflineMutation.client_mutation_id == mutation.client_mutation_id,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                await session.rollback()
                raise _error(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Client mutation ID payload differs",
                )
            replayed += 1
            results.append(
                SyncPushResult(
                    client_mutation_id=mutation.client_mutation_id,
                    client_version=mutation.client_version,
                    server_cursor=encode_cursor(
                        user_id=actor_id,
                        device_id=device_id,
                        cursor=existing.server_cursor,
                        settings=settings,
                    ),
                    status="REPLAYED",
                )
            )
            last_version = max(last_version, mutation.client_version)
            continue
        if mutation.client_version <= last_version:
            await session.rollback()
            raise _error(
                409,
                "SYNC_CLIENT_VERSION_STALE",
                "Client mutation version is not newer than device state",
            )
        await _validate_mutation_target(
            session,
            user_id=actor_id,
            mutation=mutation,
        )
        cursor_result = await session.execute(
            update(UserSyncCounter)
            .execution_options(synchronize_session=False)
            .where(UserSyncCounter.user_id == actor_id)
            .values(next_cursor=UserSyncCounter.next_cursor + 1)
            .returning(UserSyncCounter.next_cursor)
        )
        server_cursor = cursor_result.scalar_one() - 1
        session.add(
            OfflineMutation(
                user_id=actor_id,
                device_id=device_id,
                client_mutation_id=mutation.client_mutation_id,
                client_version=mutation.client_version,
                entity_type=mutation.entity_type,
                entity_id=mutation.entity_id,
                operation=mutation.operation,
                payload=mutation.payload,
                request_hash=request_hash,
                server_cursor=server_cursor,
            )
        )
        accepted += 1
        last_version = mutation.client_version
        results.append(
            SyncPushResult(
                client_mutation_id=mutation.client_mutation_id,
                client_version=mutation.client_version,
                server_cursor=encode_cursor(
                    user_id=actor_id,
                    device_id=device_id,
                    cursor=server_cursor,
                    settings=settings,
                ),
                status="APPLIED",
            )
        )
    state.last_client_version = last_version
    state.cursor = max(state.cursor, decoded_base)
    state.updated_at = datetime.now(UTC)
    await session.commit()
    current_server_cursor = await _server_cursor(session, actor_id)
    return SyncPushResponse(
        device_id=device_id,
        accepted=accepted,
        replayed=replayed,
        server_cursor=encode_cursor(
            user_id=actor_id,
            device_id=device_id,
            cursor=current_server_cursor,
            settings=settings,
        ),
        results=results,
    )


async def pull_mutations(
    session: AsyncSession,
    *,
    user: User,
    device_id: str,
    cursor_token: str | None,
    limit: int,
    settings: Settings,
) -> SyncPullResponse:
    actor_id = user.id
    cursor = decode_cursor(
        cursor_token,
        user_id=actor_id,
        device_id=device_id,
        settings=settings,
    )
    state = await _ensure_sync_state(
        session,
        user_id=actor_id,
        device_id=device_id,
    )
    current_server_cursor = await _server_cursor(session, actor_id)
    if cursor > current_server_cursor:
        await session.rollback()
        raise _error(
            409,
            "SYNC_CURSOR_AHEAD",
            "Cursor is ahead of server state; perform full resync",
        )
    found = list(
        await session.scalars(
            select(OfflineMutation)
            .where(
                OfflineMutation.user_id == actor_id,
                OfflineMutation.server_cursor > cursor,
            )
            .order_by(OfflineMutation.server_cursor)
            .limit(limit + 1)
        )
    )
    has_more = len(found) > limit
    page = found[:limit]
    next_cursor = page[-1].server_cursor if page else cursor
    state.cursor = max(state.cursor, next_cursor)
    state.updated_at = datetime.now(UTC)
    await session.commit()
    return SyncPullResponse(
        device_id=device_id,
        cursor=encode_cursor(
            user_id=actor_id,
            device_id=device_id,
            cursor=cursor,
            settings=settings,
        ),
        next_cursor=encode_cursor(
            user_id=actor_id,
            device_id=device_id,
            cursor=next_cursor,
            settings=settings,
        ),
        has_more=has_more,
        items=[
            SyncMutationResponse(
                server_cursor=encode_cursor(
                    user_id=actor_id,
                    device_id=device_id,
                    cursor=mutation.server_cursor,
                    settings=settings,
                ),
                device_id=mutation.device_id,
                client_mutation_id=mutation.client_mutation_id,
                client_version=mutation.client_version,
                entity_type=mutation.entity_type,
                entity_id=mutation.entity_id,
                operation=mutation.operation,
                payload=mutation.payload,
                created_at=_aware(mutation.created_at),
            )
            for mutation in page
        ],
    )

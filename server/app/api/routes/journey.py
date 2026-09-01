"""Offline, sync, emergency, passport, and green-task routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_roles, require_support, require_tourist
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.journey import (
    CompleteGreenTaskRequest,
    CreateSosRequest,
    EmergencyBulletinListResponse,
    EmergencyResourceListResponse,
    GreenTaskCompletionResponse,
    GreenTaskListResponse,
    OfflineAssetContentResponse,
    OfflineManifestResponse,
    OfflinePackResponse,
    PassportCheckInRequest,
    PassportCheckInResponse,
    PassportSummaryResponse,
    SosListResponse,
    SosResponse,
    SosTransitionRequest,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncStatusResponse,
)
from app.services.offline import (
    asset_content,
    get_pack,
    latest_pack,
    manifest_response,
    pack_response,
    pull_mutations,
    push_mutations,
    sync_status,
)
from app.services.passport import (
    check_in_response,
    check_in_stamp,
    complete_green_task,
    green_completion_response,
    green_task_list,
    passport_summary,
)
from app.services.safety import (
    create_sos,
    get_sos,
    list_emergency_bulletins,
    list_emergency_resources,
    list_sos,
    sos_response,
    transition_sos,
)

router = APIRouter(tags=["journey"])
require_emergency_access = require_roles("tourist", "support")


@router.get("/offline/packs/latest", response_model=OfflinePackResponse)
async def offline_pack_latest(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflinePackResponse:
    del current_user
    return pack_response(await latest_pack(session))


@router.get(
    "/offline/packs/{pack_id}/manifest",
    response_model=OfflineManifestResponse,
)
async def offline_pack_manifest(
    pack_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
    if_none_match: Annotated[str | None, Header()] = None,
) -> OfflineManifestResponse | Response:
    del current_user
    pack = await get_pack(session, pack_id)
    etag = f'"{pack.etag}"'
    headers = {
        "Cache-Control": "private, max-age=60",
        "ETag": etag,
        "Vary": "Authorization",
    }
    supplied = {
        value.strip().removeprefix("W/")
        for value in (if_none_match or "").split(",")
        if value.strip()
    }
    if etag in supplied:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(
        content=manifest_response(pack).model_dump_json(),
        media_type="application/json",
        headers=headers,
    )


@router.get(
    "/offline/packs/{pack_id}/assets/{asset_id}",
    response_model=OfflineAssetContentResponse,
)
async def offline_pack_asset(
    pack_id: UUID,
    asset_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfflineAssetContentResponse:
    del current_user
    return await asset_content(session, pack_id=pack_id, asset_id=asset_id)


@router.get("/offline/sync/status", response_model=SyncStatusResponse)
async def offline_sync_status(
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
    device_id: Annotated[str, Query(pattern=r"^[A-Za-z0-9._:-]{4,100}$")],
) -> SyncStatusResponse:
    return await sync_status(
        session,
        user=current_user,
        device_id=device_id,
        settings=request.app.state.settings,
    )


@router.post("/offline/sync/push", response_model=SyncPushResponse)
async def offline_sync_push(
    payload: SyncPushRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SyncPushResponse:
    return await push_mutations(
        session,
        user=current_user,
        device_id=payload.device_id,
        base_cursor=payload.base_cursor,
        mutations=payload.mutations,
        settings=request.app.state.settings,
    )


@router.get("/offline/sync/pull", response_model=SyncPullResponse)
async def offline_sync_pull(
    request: Request,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
    device_id: Annotated[str, Query(pattern=r"^[A-Za-z0-9._:-]{4,100}$")],
    cursor: Annotated[str | None, Query(max_length=300)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SyncPullResponse:
    return await pull_mutations(
        session,
        user=current_user,
        device_id=device_id,
        cursor_token=cursor,
        limit=limit,
        settings=request.app.state.settings,
    )


@router.get(
    "/emergency/resources",
    response_model=EmergencyResourceListResponse,
)
async def emergency_resources(
    current_user: Annotated[User, Depends(require_emergency_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmergencyResourceListResponse:
    del current_user
    return EmergencyResourceListResponse(items=await list_emergency_resources(session))


@router.get(
    "/emergency/bulletins",
    response_model=EmergencyBulletinListResponse,
)
async def emergency_bulletins(
    current_user: Annotated[User, Depends(require_emergency_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EmergencyBulletinListResponse:
    del current_user
    return EmergencyBulletinListResponse(items=await list_emergency_bulletins(session))


@router.post(
    "/emergency/sos",
    response_model=SosResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_sos(
    payload: CreateSosRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SosResponse:
    return sos_response(
        await create_sos(
            session,
            user=current_user,
            kind=payload.kind,
            message=payload.message,
            node_id=payload.node_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.get("/emergency/sos", response_model=SosListResponse)
async def sos_items(
    current_user: Annotated[User, Depends(require_emergency_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SosListResponse:
    return SosListResponse(
        items=[sos_response(item) for item in await list_sos(session, user=current_user)]
    )


@router.get("/emergency/sos/{sos_id}", response_model=SosResponse)
async def sos_detail(
    sos_id: UUID,
    current_user: Annotated[User, Depends(require_emergency_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SosResponse:
    return sos_response(
        await get_sos(
            session,
            sos_id=sos_id,
            user=current_user,
        )
    )


async def _transition_sos_route(
    *,
    sos_id: UUID,
    current_user: User,
    session: AsyncSession,
    target_status: str,
) -> SosResponse:
    return sos_response(
        await transition_sos(
            session,
            sos_id=sos_id,
            actor=current_user,
            target_status=target_status,
        )
    )


@router.put("/emergency/sos/{sos_id}/acknowledge", response_model=SosResponse)
async def acknowledge_sos(
    sos_id: UUID,
    payload: SosTransitionRequest,
    current_user: Annotated[User, Depends(require_support)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SosResponse:
    del payload
    return await _transition_sos_route(
        sos_id=sos_id,
        current_user=current_user,
        session=session,
        target_status="ACKNOWLEDGED",
    )


@router.put("/emergency/sos/{sos_id}/resolve", response_model=SosResponse)
async def resolve_sos(
    sos_id: UUID,
    payload: SosTransitionRequest,
    current_user: Annotated[User, Depends(require_support)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SosResponse:
    del payload
    return await _transition_sos_route(
        sos_id=sos_id,
        current_user=current_user,
        session=session,
        target_status="RESOLVED",
    )


@router.get("/passport", response_model=PassportSummaryResponse)
async def passport(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PassportSummaryResponse:
    return await passport_summary(session, user=current_user)


@router.post("/passport/check-ins", response_model=PassportCheckInResponse)
async def passport_check_in(
    payload: PassportCheckInRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PassportCheckInResponse:
    stamp, balance = await check_in_stamp(
        session,
        user=current_user,
        stamp_code=payload.stamp_code,
        idempotency_key=payload.idempotency_key,
    )
    return check_in_response(stamp, point_balance=balance)


@router.get("/green/tasks", response_model=GreenTaskListResponse)
async def green_tasks(
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GreenTaskListResponse:
    return await green_task_list(session, user=current_user)


@router.post(
    "/green/tasks/{task_id}/complete",
    response_model=GreenTaskCompletionResponse,
)
async def complete_green_task_item(
    task_id: UUID,
    payload: CompleteGreenTaskRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GreenTaskCompletionResponse:
    completion, balance = await complete_green_task(
        session,
        user=current_user,
        task_id=task_id,
        evidence=payload.evidence,
        idempotency_key=payload.idempotency_key,
    )
    return green_completion_response(completion, point_balance=balance)

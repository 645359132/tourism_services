"""Travel-group invites, shared itinerary links, privacy, status, and lost alerts."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models.engagement import (
    GroupMember,
    LostAlert,
    MeetingPoint,
    TravelGroup,
)
from app.db.models.guide import Itinerary, RouteNode
from app.db.models.user import User
from app.schemas.engagement import (
    GroupMemberResponse,
    GroupResponse,
    LostAlertResponse,
    MeetingPointResponse,
)


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _group_statement():
    return (
        select(TravelGroup)
        .execution_options(populate_existing=True)
        .options(
            selectinload(TravelGroup.members),
            selectinload(TravelGroup.meeting_points),
        )
    )


async def _load_group(session: AsyncSession, group_id: UUID) -> TravelGroup | None:
    return await session.scalar(_group_statement().where(TravelGroup.id == group_id))


def _member(group: TravelGroup, user_id: UUID) -> GroupMember | None:
    return next((member for member in group.members if member.user_id == user_id), None)


async def accessible_group(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
) -> tuple[TravelGroup, GroupMember]:
    group = await _load_group(session, group_id)
    if group is None or not group.is_active:
        raise _error(404, "GROUP_NOT_FOUND", "Travel group not found")
    member = _member(group, user.id)
    if member is None:
        raise _error(404, "GROUP_NOT_FOUND", "Travel group not found")
    return group, member


async def group_response(
    session: AsyncSession,
    *,
    group: TravelGroup,
    viewer: User,
) -> GroupResponse:
    viewer_member = _member(group, viewer.id)
    if viewer_member is None:
        raise _error(404, "GROUP_NOT_FOUND", "Travel group not found")
    users = {
        user.id: user
        for user in await session.scalars(
            select(User).where(User.id.in_([member.user_id for member in group.members]))
        )
    }
    # 创新点 5: 位置和状态采用“群组总开关 ∩ 成员本人授权”的双层隐私模型;
    # 任意一层关闭都在响应组装时脱敏, 不能靠客户端隐藏来代替服务端授权。
    members = [
        GroupMemberResponse(
            user_id=str(member.user_id),
            display_name=users[member.user_id].display_name,
            role=member.role,
            status=(
                member.status if group.share_member_status and member.share_status else "HIDDEN"
            ),
            share_location=group.share_location and member.share_location,
            share_status=group.share_member_status and member.share_status,
            note=(member.note if group.share_member_status and member.share_status else ""),
            updated_at=_aware(member.updated_at),
            latitude=(
                member.latitude_e6 / 1_000_000
                if group.share_location and member.share_location and member.latitude_e6 is not None
                else None
            ),
            longitude=(
                member.longitude_e6 / 1_000_000
                if group.share_location
                and member.share_location
                and member.longitude_e6 is not None
                else None
            ),
        )
        for member in sorted(
            group.members,
            key=lambda value: (value.role != "OWNER", str(value.id)),
        )
    ]
    latest_meeting = max(
        group.meeting_points,
        key=lambda point: _aware(point.created_at),
        default=None,
    )
    meeting = (
        None
        if latest_meeting is None
        else MeetingPointResponse(
            id=str(latest_meeting.id),
            name=latest_meeting.name,
            node_id=(None if latest_meeting.node_id is None else str(latest_meeting.node_id)),
            note=latest_meeting.description,
            created_at=_aware(latest_meeting.created_at),
        )
    )
    itinerary = (
        None if group.itinerary_id is None else await session.get(Itinerary, group.itinerary_id)
    )
    return GroupResponse(
        id=str(group.id),
        name=group.name,
        invite_code=group.invite_code,
        revision=group.revision,
        itinerary_id=(
            None
            if group.itinerary_id is None or not group.share_itinerary
            else str(group.itinerary_id)
        ),
        itinerary_revision=(
            None if itinerary is None or not group.share_itinerary else itinerary.revision
        ),
        share_itinerary=group.share_itinerary,
        share_location=group.share_location,
        share_member_status=group.share_member_status,
        members=members,
        meeting_point=meeting,
        provider="local_collaboration",
        is_demo=True,
        updated_at=_aware(group.updated_at),
    )


async def create_group(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    invite_valid_minutes: int,
    itinerary_id: UUID | None,
) -> TravelGroup:
    if itinerary_id is not None:
        itinerary = await session.get(Itinerary, itinerary_id)
        if itinerary is None or itinerary.user_id != user.id:
            raise _error(404, "ITINERARY_NOT_FOUND", "Itinerary not found")
    group = TravelGroup(
        name=name.strip(),
        owner_user_id=user.id,
        invite_code=secrets.token_hex(4).upper(),
        invite_expires_at=datetime.now(UTC) + timedelta(minutes=invite_valid_minutes),
        itinerary_id=itinerary_id,
        revision=1,
        share_itinerary=True,
        share_location=False,
        share_member_status=True,
        is_active=True,
    )
    group.members.append(
        GroupMember(
            user_id=user.id,
            role="OWNER",
            share_location=False,
            share_status=True,
            status="TOGETHER",
            note="",
        )
    )
    session.add(group)
    await session.commit()
    loaded = await _load_group(session, group.id)
    assert loaded is not None
    return loaded


async def join_group(
    session: AsyncSession,
    *,
    user: User,
    invite_code: str,
) -> TravelGroup:
    group = await session.scalar(
        _group_statement().where(
            TravelGroup.invite_code == invite_code.strip().upper(),
            TravelGroup.is_active.is_(True),
        )
    )
    if group is None:
        raise _error(404, "INVITE_NOT_FOUND", "Invite code is invalid")
    if _aware(group.invite_expires_at) <= datetime.now(UTC):
        raise _error(409, "INVITE_EXPIRED", "Invite code has expired")
    if _member(group, user.id) is not None:
        return group
    group.members.append(
        GroupMember(
            user_id=user.id,
            role="MEMBER",
            share_location=False,
            share_status=False,
            status="TOGETHER",
            note="",
        )
    )
    group.revision += 1
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        concurrent = await session.scalar(_group_statement().where(TravelGroup.id == group.id))
        if concurrent is None or _member(concurrent, user.id) is None:
            raise _error(409, "GROUP_JOIN_CONFLICT", "Could not join group") from exc
    loaded = await _load_group(session, group.id)
    assert loaded is not None
    return loaded


async def get_group(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
) -> TravelGroup:
    group, _ = await accessible_group(
        session,
        group_id=group_id,
        user=user,
    )
    return group


async def update_group_privacy(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
    share_itinerary: bool,
    share_location: bool,
    share_member_status: bool,
) -> TravelGroup:
    group, member = await accessible_group(
        session,
        group_id=group_id,
        user=user,
    )
    if member.role != "OWNER":
        raise _error(403, "FORBIDDEN", "Only the group owner can update privacy")
    transitioned = await session.execute(
        update(TravelGroup)
        .execution_options(synchronize_session=False)
        .where(
            TravelGroup.id == group.id,
            TravelGroup.revision == group.revision,
        )
        .values(
            share_itinerary=share_itinerary,
            share_location=share_location,
            share_member_status=share_member_status,
            revision=TravelGroup.revision + 1,
            updated_at=datetime.now(UTC),
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "GROUP_REVISION_CONFLICT", "Group revision changed")
    # 创新点 5: 关闭群组位置共享时同步擦除历史坐标, 防止以后重新开启时意外暴露旧位置。
    for group_member in group.members:
        if not share_location:
            group_member.latitude_e6 = None
            group_member.longitude_e6 = None
    await session.commit()
    loaded = await _load_group(session, group.id)
    assert loaded is not None
    return loaded


async def link_group_itinerary(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
    itinerary_id: UUID | None,
    expected_revision: int,
) -> TravelGroup:
    group, member = await accessible_group(
        session,
        group_id=group_id,
        user=user,
    )
    if member.role != "OWNER":
        raise _error(403, "FORBIDDEN", "Only the group owner can link itinerary")
    if itinerary_id is not None:
        itinerary = await session.get(Itinerary, itinerary_id)
        if itinerary is None or itinerary.user_id != user.id:
            raise _error(404, "ITINERARY_NOT_FOUND", "Itinerary not found")
    transitioned = await session.execute(
        update(TravelGroup)
        .execution_options(synchronize_session=False)
        .where(
            TravelGroup.id == group.id,
            TravelGroup.revision == expected_revision,
        )
        .values(
            itinerary_id=itinerary_id,
            revision=TravelGroup.revision + 1,
            updated_at=datetime.now(UTC),
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "GROUP_REVISION_CONFLICT", "Group revision changed")
    await session.commit()
    loaded = await _load_group(session, group.id)
    assert loaded is not None
    return loaded


async def create_meeting_point(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
    name: str,
    note: str,
    node_id: UUID | None,
    meeting_at: datetime | None,
) -> MeetingPoint:
    group, _ = await accessible_group(
        session,
        group_id=group_id,
        user=user,
    )
    if node_id is not None and await session.get(RouteNode, node_id) is None:
        raise _error(404, "ROUTE_NODE_NOT_FOUND", "Route node not found")
    point = MeetingPoint(
        group_id=group.id,
        created_by_user_id=user.id,
        name=name.strip(),
        description=note.strip(),
        node_id=node_id,
        meeting_at=meeting_at,
    )
    session.add(point)
    group.revision += 1
    await session.commit()
    await session.refresh(point)
    return point


async def update_member_status(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
    status: str,
    note: str,
    share_location: bool | None,
    share_status: bool | None,
    latitude: float | None,
    longitude: float | None,
) -> TravelGroup:
    group, member = await accessible_group(
        session,
        group_id=group_id,
        user=user,
    )
    member.status = status
    member.note = note.strip()
    if share_location is not None:
        member.share_location = share_location
    if share_status is not None:
        member.share_status = share_status
    member.last_seen_at = datetime.now(UTC)
    if group.share_location and member.share_location and latitude is not None:
        assert longitude is not None
        member.latitude_e6 = round(latitude * 1_000_000)
        member.longitude_e6 = round(longitude * 1_000_000)
    elif latitude is not None or not member.share_location:
        member.latitude_e6 = None
        member.longitude_e6 = None
    group.revision += 1
    await session.commit()
    loaded = await _load_group(session, group.id)
    assert loaded is not None
    return loaded


def lost_alert_response(alert: LostAlert) -> LostAlertResponse:
    return LostAlertResponse(
        id=str(alert.id),
        group_id=str(alert.group_id),
        status=alert.status,
        message=alert.message,
        last_seen_node_id=(
            None if alert.last_seen_node_id is None else str(alert.last_seen_node_id)
        ),
        provider="local_collaboration",
        is_demo=True,
        created_at=_aware(alert.created_at),
    )


async def create_lost_alert(
    session: AsyncSession,
    *,
    group_id: UUID,
    user: User,
    target_member_id: UUID | None,
    message: str,
    last_seen_node_id: UUID | None,
) -> LostAlert:
    group, reporter = await accessible_group(
        session,
        group_id=group_id,
        user=user,
    )
    target = (
        reporter
        if target_member_id is None
        else next(
            (member for member in group.members if member.id == target_member_id),
            None,
        )
    )
    if target is None:
        raise _error(404, "GROUP_MEMBER_NOT_FOUND", "Target member not found")
    if target.id != reporter.id and reporter.role != "OWNER":
        raise _error(403, "FORBIDDEN", "Only the owner can report another member")
    if last_seen_node_id is not None and await session.get(RouteNode, last_seen_node_id) is None:
        raise _error(404, "ROUTE_NODE_NOT_FOUND", "Last seen node not found")
    alert = LostAlert(
        group_id=group.id,
        reporter_user_id=user.id,
        target_member_id=target.id,
        last_seen_node_id=last_seen_node_id,
        message=message.strip(),
        status="ACTIVE",
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert

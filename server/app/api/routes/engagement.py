"""Feedback, FAQs, group collaboration, and facility routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import require_roles, require_support, require_tourist
from app.db.models.user import User
from app.db.session import get_session
from app.schemas.engagement import (
    AssignFeedbackRequest,
    CreateFeedbackRequest,
    CreateGroupRequest,
    FacilityListResponse,
    FAQListResponse,
    FeedbackFollowUpRequest,
    FeedbackListResponse,
    FeedbackResponse,
    GroupItineraryRequest,
    GroupPrivacyRequest,
    GroupResponse,
    JoinGroupRequest,
    LostAlertRequest,
    LostAlertResponse,
    MeetingPointRequest,
    MemberStatusRequest,
    ResolveFeedbackRequest,
)
from app.services.engagement import (
    assign_feedback,
    create_feedback,
    feedback_response,
    follow_up_feedback,
    get_feedback,
    list_facilities,
    list_faqs,
    list_feedback,
    resolve_feedback,
)
from app.services.groups import (
    create_group,
    create_lost_alert,
    create_meeting_point,
    get_group,
    group_response,
    join_group,
    link_group_itinerary,
    lost_alert_response,
    update_group_privacy,
    update_member_status,
)

router = APIRouter(tags=["engagement"])
require_feedback_access = require_roles("tourist", "support")


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    payload: CreateFeedbackRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    feedback = await create_feedback(
        session,
        user=current_user,
        kind=payload.kind,
        title=payload.title,
        content=payload.content,
        priority=payload.priority,
    )
    return feedback_response(feedback)


@router.get("/feedback", response_model=FeedbackListResponse)
async def feedback_items(
    current_user: Annotated[User, Depends(require_feedback_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FeedbackListResponse:
    items, total = await list_feedback(
        session,
        user=current_user,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return FeedbackListResponse(
        items=[feedback_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/feedback/{feedback_id}", response_model=FeedbackResponse)
async def feedback_detail(
    feedback_id: UUID,
    current_user: Annotated[User, Depends(require_feedback_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    return feedback_response(
        await get_feedback(
            session,
            feedback_id=feedback_id,
            user=current_user,
        )
    )


@router.post("/feedback/{feedback_id}/assign", response_model=FeedbackResponse)
async def assign_feedback_item(
    feedback_id: UUID,
    payload: AssignFeedbackRequest,
    current_user: Annotated[User, Depends(require_support)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    return feedback_response(
        await assign_feedback(
            session,
            feedback_id=feedback_id,
            actor=current_user,
            assigned_to_user_id=payload.assigned_to_user_id,
            note=payload.note,
        )
    )


@router.post("/feedback/{feedback_id}/resolve", response_model=FeedbackResponse)
async def resolve_feedback_item(
    feedback_id: UUID,
    payload: ResolveFeedbackRequest,
    current_user: Annotated[User, Depends(require_support)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    return feedback_response(
        await resolve_feedback(
            session,
            feedback_id=feedback_id,
            actor=current_user,
            resolution=payload.resolution,
        )
    )


async def _feedback_follow_up(
    feedback_id: UUID,
    payload: FeedbackFollowUpRequest,
    current_user: User,
    session: AsyncSession,
) -> FeedbackResponse:
    return feedback_response(
        await follow_up_feedback(
            session,
            feedback_id=feedback_id,
            user=current_user,
            rating=payload.rating,
            comment=payload.comment,
        )
    )


@router.post("/feedback/{feedback_id}/follow-up", response_model=FeedbackResponse)
async def follow_up_feedback_item(
    feedback_id: UUID,
    payload: FeedbackFollowUpRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    return await _feedback_follow_up(
        feedback_id,
        payload,
        current_user,
        session,
    )


@router.post("/feedback/{feedback_id}/rating", response_model=FeedbackResponse)
async def rate_feedback_item(
    feedback_id: UUID,
    payload: FeedbackFollowUpRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FeedbackResponse:
    return await _feedback_follow_up(
        feedback_id,
        payload,
        current_user,
        session,
    )


@router.get("/faqs", response_model=FAQListResponse)
async def faqs(
    session: Annotated[AsyncSession, Depends(get_session)],
    category: Annotated[str | None, Query(max_length=50)] = None,
) -> FAQListResponse:
    return FAQListResponse(items=await list_faqs(session, category=category))


@router.get("/guide/facilities", response_model=FacilityListResponse)
async def facilities(
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str | None, Query(max_length=40)] = None,
    accessible_only: Annotated[bool, Query()] = False,
) -> FacilityListResponse:
    return FacilityListResponse(
        items=await list_facilities(
            session,
            kind=kind,
            accessible_only=accessible_only,
        )
    )


@router.post(
    "/groups/create",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_travel_group(
    payload: CreateGroupRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    group = await create_group(
        session,
        user=current_user,
        name=payload.name,
        invite_valid_minutes=payload.invite_valid_minutes,
        itinerary_id=payload.itinerary_id,
    )
    return await group_response(session, group=group, viewer=current_user)


@router.post("/groups/join", response_model=GroupResponse)
async def join_travel_group(
    payload: JoinGroupRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    group = await join_group(
        session,
        user=current_user,
        invite_code=payload.invite_code,
    )
    return await group_response(session, group=group, viewer=current_user)


@router.get("/groups/{group_id}", response_model=GroupResponse)
async def travel_group_detail(
    group_id: UUID,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    group = await get_group(session, group_id=group_id, user=current_user)
    return await group_response(session, group=group, viewer=current_user)


@router.patch("/groups/{group_id}/privacy", response_model=GroupResponse)
@router.put("/groups/{group_id}/privacy", response_model=GroupResponse)
async def patch_group_privacy(
    group_id: UUID,
    payload: GroupPrivacyRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    group = await update_group_privacy(
        session,
        group_id=group_id,
        user=current_user,
        share_itinerary=payload.share_itinerary,
        share_location=payload.share_location,
        share_member_status=payload.share_member_status,
    )
    return await group_response(session, group=group, viewer=current_user)


@router.patch("/groups/{group_id}/itinerary", response_model=GroupResponse)
@router.put("/groups/{group_id}/itinerary", response_model=GroupResponse)
async def patch_group_itinerary(
    group_id: UUID,
    payload: GroupItineraryRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    group = await link_group_itinerary(
        session,
        group_id=group_id,
        user=current_user,
        itinerary_id=payload.itinerary_id,
        expected_revision=payload.expected_revision,
    )
    return await group_response(session, group=group, viewer=current_user)


@router.post(
    "/groups/{group_id}/meeting-points",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_meeting_point(
    group_id: UUID,
    payload: MeetingPointRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    await create_meeting_point(
        session,
        group_id=group_id,
        user=current_user,
        name=payload.name,
        note=payload.note,
        node_id=payload.node_id,
        meeting_at=payload.meeting_at,
    )
    group = await get_group(session, group_id=group_id, user=current_user)
    return await group_response(session, group=group, viewer=current_user)


@router.post("/groups/{group_id}/member-status", response_model=GroupResponse)
async def update_group_member_status(
    group_id: UUID,
    payload: MemberStatusRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GroupResponse:
    group = await update_member_status(
        session,
        group_id=group_id,
        user=current_user,
        status=payload.status,
        note=payload.note,
        share_location=payload.share_location,
        share_status=payload.share_status,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    return await group_response(session, group=group, viewer=current_user)


@router.post(
    "/groups/{group_id}/lost-alerts",
    response_model=LostAlertResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_lost_alert(
    group_id: UUID,
    payload: LostAlertRequest,
    current_user: Annotated[User, Depends(require_tourist)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LostAlertResponse:
    alert = await create_lost_alert(
        session,
        group_id=group_id,
        user=current_user,
        target_member_id=payload.target_member_id,
        message=payload.message,
        last_seen_node_id=payload.last_seen_node_id,
    )
    return lost_alert_response(alert)

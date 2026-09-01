"""Feedback state machine, FAQs, and accessible facility discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models.engagement import (
    FAQ,
    FacilityPOI,
    Feedback,
    FeedbackEvent,
    FeedbackFollowUp,
)
from app.db.models.user import User
from app.schemas.engagement import (
    FacilityResponse,
    FAQResponse,
    FeedbackFollowUpResponse,
    FeedbackResponse,
)
from app.services.auth import get_user_by_id


def _error(status_code: int, code: str, message: str) -> AppError:
    return AppError(status_code=status_code, code=code, message=message)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_staff(user: User) -> bool:
    return bool({"support", "admin"}.intersection(user.role_names))


def _feedback_statement():
    return (
        select(Feedback)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Feedback.events),
            selectinload(Feedback.follow_up),
        )
    )


async def _load_feedback(
    session: AsyncSession,
    feedback_id: UUID,
) -> Feedback | None:
    return await session.scalar(_feedback_statement().where(Feedback.id == feedback_id))


async def _visible_feedback(
    session: AsyncSession,
    *,
    feedback_id: UUID,
    user: User,
) -> Feedback:
    feedback = await _load_feedback(session, feedback_id)
    if feedback is None or (feedback.user_id != user.id and not _is_staff(user)):
        raise _error(404, "FEEDBACK_NOT_FOUND", "Feedback not found")
    return feedback


def feedback_response(feedback: Feedback) -> FeedbackResponse:
    follow_ups = (
        []
        if feedback.follow_up is None
        else [
            FeedbackFollowUpResponse(
                id=str(feedback.follow_up.id),
                author_name="游客",
                rating=feedback.follow_up.rating,
                comment=feedback.follow_up.comment,
                created_at=_aware(feedback.follow_up.created_at),
            )
        ]
    )
    latest_event_note = next(
        (event.note for event in reversed(feedback.events) if event.note is not None),
        None,
    )
    return FeedbackResponse(
        id=str(feedback.id),
        ticket_no=feedback.ticket_no,
        kind=feedback.category,
        title=feedback.subject,
        content=feedback.content,
        status=feedback.status,
        priority=feedback.priority,
        latest_response=feedback.resolution or latest_event_note,
        rating=None if feedback.follow_up is None else feedback.follow_up.rating,
        follow_ups=follow_ups,
        created_at=_aware(feedback.created_at),
        updated_at=_aware(feedback.updated_at),
    )


async def create_feedback(
    session: AsyncSession,
    *,
    user: User,
    kind: str,
    title: str,
    content: str,
    priority: str,
) -> Feedback:
    feedback = Feedback(
        ticket_no=f"FB-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}",
        user_id=user.id,
        category=kind,
        subject=title.strip(),
        content=content.strip(),
        status="SUBMITTED",
        priority=priority,
    )
    feedback.events.append(
        FeedbackEvent(
            actor_user_id=user.id,
            action="SUBMIT",
            from_status=None,
            to_status="SUBMITTED",
            note="游客提交",
        )
    )
    session.add(feedback)
    await session.commit()
    loaded = await _load_feedback(session, feedback.id)
    assert loaded is not None
    return loaded


async def list_feedback(session: AsyncSession, *, user: User) -> list[Feedback]:
    statement = _feedback_statement().order_by(Feedback.created_at.desc())
    if not _is_staff(user):
        statement = statement.where(Feedback.user_id == user.id)
    return list(await session.scalars(statement))


async def get_feedback(
    session: AsyncSession,
    *,
    feedback_id: UUID,
    user: User,
) -> Feedback:
    return await _visible_feedback(
        session,
        feedback_id=feedback_id,
        user=user,
    )


async def assign_feedback(
    session: AsyncSession,
    *,
    feedback_id: UUID,
    actor: User,
    assigned_to_user_id: UUID | None,
    note: str | None,
) -> Feedback:
    if not _is_staff(actor):
        raise _error(403, "FORBIDDEN", "Support role required")
    feedback = await _visible_feedback(
        session,
        feedback_id=feedback_id,
        user=actor,
    )
    if feedback.status not in {"SUBMITTED", "IN_PROGRESS"}:
        raise _error(409, "FEEDBACK_NOT_ASSIGNABLE", "Feedback is not assignable")
    assignee_id = assigned_to_user_id or actor.id
    assignee = await get_user_by_id(session, assignee_id)
    if assignee is None or not _is_staff(assignee):
        raise _error(422, "INVALID_ASSIGNEE", "Assignee must have support role")
    previous = feedback.status
    transitioned = await session.execute(
        update(Feedback)
        .execution_options(synchronize_session=False)
        .where(
            Feedback.id == feedback.id,
            Feedback.status == previous,
            Feedback.version == feedback.version,
        )
        .values(
            status="IN_PROGRESS",
            assigned_to_user_id=assignee_id,
            version=Feedback.version + 1,
            updated_at=datetime.now(UTC),
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "FEEDBACK_CONFLICT", "Feedback changed concurrently")
    session.add(
        FeedbackEvent(
            feedback_id=feedback.id,
            actor_user_id=actor.id,
            action="ASSIGN",
            from_status=previous,
            to_status="IN_PROGRESS",
            note=note.strip() if note else "已分配客服",
        )
    )
    await session.commit()
    loaded = await _load_feedback(session, feedback.id)
    assert loaded is not None
    return loaded


async def resolve_feedback(
    session: AsyncSession,
    *,
    feedback_id: UUID,
    actor: User,
    resolution: str,
) -> Feedback:
    if not _is_staff(actor):
        raise _error(403, "FORBIDDEN", "Support role required")
    feedback = await _visible_feedback(
        session,
        feedback_id=feedback_id,
        user=actor,
    )
    if feedback.status != "IN_PROGRESS":
        raise _error(409, "FEEDBACK_NOT_RESOLVABLE", "Feedback is not in progress")
    if feedback.assigned_to_user_id != actor.id and "admin" not in actor.role_names:
        raise _error(403, "FORBIDDEN", "Only the assignee can resolve feedback")
    now = datetime.now(UTC)
    transitioned = await session.execute(
        update(Feedback)
        .execution_options(synchronize_session=False)
        .where(
            Feedback.id == feedback.id,
            Feedback.status == "IN_PROGRESS",
            Feedback.version == feedback.version,
        )
        .values(
            status="RESOLVED",
            resolution=resolution.strip(),
            resolved_at=now,
            updated_at=now,
            version=Feedback.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "FEEDBACK_CONFLICT", "Feedback changed concurrently")
    session.add(
        FeedbackEvent(
            feedback_id=feedback.id,
            actor_user_id=actor.id,
            action="RESOLVE",
            from_status="IN_PROGRESS",
            to_status="RESOLVED",
            note=resolution.strip(),
        )
    )
    await session.commit()
    loaded = await _load_feedback(session, feedback.id)
    assert loaded is not None
    return loaded


async def follow_up_feedback(
    session: AsyncSession,
    *,
    feedback_id: UUID,
    user: User,
    rating: int,
    comment: str,
) -> Feedback:
    feedback = await _visible_feedback(
        session,
        feedback_id=feedback_id,
        user=user,
    )
    if feedback.user_id != user.id:
        raise _error(403, "FORBIDDEN", "Only the feedback owner can rate resolution")
    if feedback.status != "RESOLVED":
        raise _error(409, "FOLLOW_UP_NOT_ALLOWED", "Feedback is not resolved")
    if feedback.follow_up is not None:
        raise _error(409, "FOLLOW_UP_EXISTS", "Feedback was already rated")
    transitioned = await session.execute(
        update(Feedback)
        .execution_options(synchronize_session=False)
        .where(
            Feedback.id == feedback.id,
            Feedback.status == "RESOLVED",
            Feedback.version == feedback.version,
        )
        .values(
            status="CLOSED",
            updated_at=datetime.now(UTC),
            version=Feedback.version + 1,
        )
    )
    if transitioned.rowcount != 1:
        await session.rollback()
        raise _error(409, "FEEDBACK_CONFLICT", "Feedback changed concurrently")
    session.add(
        FeedbackFollowUp(
            feedback_id=feedback.id,
            user_id=user.id,
            rating=rating,
            comment=comment.strip(),
        )
    )
    session.add(
        FeedbackEvent(
            feedback_id=feedback.id,
            actor_user_id=user.id,
            action="FOLLOW_UP",
            from_status="RESOLVED",
            to_status="CLOSED",
            note=comment.strip(),
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _error(409, "FOLLOW_UP_EXISTS", "Feedback was already rated") from exc
    loaded = await _load_feedback(session, feedback.id)
    assert loaded is not None
    return loaded


async def list_faqs(
    session: AsyncSession,
    *,
    category: str | None = None,
) -> list[FAQResponse]:
    statement = select(FAQ).where(FAQ.is_active.is_(True)).order_by(FAQ.sort_order, FAQ.code)
    if category is not None:
        statement = statement.where(FAQ.category == category)
    faqs = list(await session.scalars(statement))
    return [
        FAQResponse(
            id=str(faq.id),
            category=faq.category,
            question=faq.question,
            answer=faq.answer,
            sort_order=faq.sort_order,
        )
        for faq in faqs
    ]


async def list_facilities(
    session: AsyncSession,
    *,
    kind: str | None = None,
    accessible_only: bool = False,
) -> list[FacilityResponse]:
    statement = select(FacilityPOI).order_by(FacilityPOI.code)
    if kind is not None:
        statement = statement.where(FacilityPOI.category == kind)
    if accessible_only:
        statement = statement.where(
            FacilityPOI.accessible.is_(True),
            FacilityPOI.wheelchair_ok.is_(True),
        )
    facilities = list(await session.scalars(statement))
    return [
        FacilityResponse(
            id=str(facility.id),
            kind=facility.category,
            name=facility.name,
            description=facility.description,
            node_id=None if facility.node_id is None else str(facility.node_id),
            accessible=facility.accessible,
            wheelchair_ok=facility.wheelchair_ok,
            stroller_ok=facility.stroller_accessible,
            open_status=facility.open_status,
            source=facility.source,
            is_demo=facility.is_demo,
        )
        for facility in facilities
    ]

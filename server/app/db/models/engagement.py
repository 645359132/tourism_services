"""Feedback, support, travel-group, and accessible facility models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "category IN ('FEEDBACK', 'COMPLAINT', 'SUGGESTION')",
            name="valid_category",
        ),
        CheckConstraint(
            "status IN ('SUBMITTED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')",
            name="valid_status",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'NORMAL', 'HIGH')",
            name="valid_priority",
        ),
        Index("ix_feedback_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_no: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="SUBMITTED",
    )
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="NORMAL",
    )
    assigned_to_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    events: Mapped[list[FeedbackEvent]] = relationship(
        back_populates="feedback",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="FeedbackEvent.created_at",
    )
    follow_up: Mapped[FeedbackFollowUp | None] = relationship(
        back_populates="feedback",
        cascade="all, delete-orphan",
        lazy="selectin",
        uselist=False,
    )


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    feedback_id: Mapped[UUID] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    feedback: Mapped[Feedback] = relationship(back_populates="events")


class FeedbackFollowUp(Base):
    __tablename__ = "feedback_followups"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    feedback_id: Mapped[UUID] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    feedback: Mapped[Feedback] = relationship(back_populates="follow_up")


class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answer: Mapped[str] = mapped_column(String(2000), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class SupportConversation(Base):
    __tablename__ = "support_conversations"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="valid_status"),
        CheckConstraint("mode IN ('DEMO_BOT', 'LIVE')", name="valid_mode"),
        Index("ix_support_conversations_tourist_created", "tourist_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_no: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    tourist_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_support_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="DEMO_BOT")
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list[SupportMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SupportMessage.sequence",
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_support_messages_sequence",
        ),
        UniqueConstraint(
            "conversation_id",
            "sender_key",
            "idempotency_key",
            name="uq_support_messages_sender_idempotency",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "sender_type IN ('TOURIST', 'SUPPORT', 'BOT')",
            name="valid_sender_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sender_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="human")
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    conversation: Mapped[SupportConversation] = relationship(back_populates="messages")


class TravelGroup(Base):
    __tablename__ = "travel_groups"
    __table_args__ = (CheckConstraint("revision > 0", name="revision_positive"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    invite_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    invite_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    itinerary_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("itineraries.id", ondelete="SET NULL"),
        nullable=True,
    )
    share_itinerary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    share_location: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    share_member_status: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    members: Mapped[list[GroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    meeting_points: Mapped[list[MeetingPoint]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MeetingPoint.created_at",
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_members_user"),
        CheckConstraint("role IN ('OWNER', 'MEMBER')", name="valid_role"),
        CheckConstraint(
            "status IN ('TOGETHER', 'MOVING', 'WAITING', 'LOST')",
            name="valid_status",
        ),
        CheckConstraint(
            "latitude_e6 IS NULL OR (latitude_e6 >= -90000000 AND latitude_e6 <= 90000000)",
            name="latitude_range",
        ),
        CheckConstraint(
            "longitude_e6 IS NULL OR (longitude_e6 >= -180000000 AND longitude_e6 <= 180000000)",
            name="longitude_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("travel_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="MEMBER")
    share_location: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    share_status: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="TOGETHER",
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    latitude_e6: Mapped[int | None] = mapped_column(Integer, nullable=True)
    longitude_e6: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    group: Mapped[TravelGroup] = relationship(back_populates="members")


class MeetingPoint(Base):
    __tablename__ = "meeting_points"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("travel_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    meeting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    group: Mapped[TravelGroup] = relationship(back_populates="meeting_points")


class LostAlert(Base):
    __tablename__ = "lost_alerts"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'RESOLVED')", name="valid_status"),
        Index("ix_lost_alerts_group_status", "group_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("travel_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_member_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_seen_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FacilityPOI(Base):
    __tablename__ = "facility_pois"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(800), nullable=False)
    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    accessible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    wheelchair_ok: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    stroller_accessible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    baby_care: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    open_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="OPEN",
        server_default="OPEN",
    )
    source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="curated_demo",
        server_default="curated_demo",
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

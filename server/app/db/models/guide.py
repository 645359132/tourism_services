"""Scenic guide graph, simulated crowd, and rule-planned itinerary models."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Attraction(Base):
    __tablename__ = "attractions"
    __table_args__ = (CheckConstraint("visit_minutes > 0", name="visit_minutes_positive"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    visit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    accessibility: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

    narrations: Mapped[list[Narration]] = relationship(
        back_populates="attraction",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Narration(Base):
    __tablename__ = "narrations"
    __table_args__ = (
        UniqueConstraint(
            "attraction_id",
            "language",
            name="uq_narrations_attraction_language",
        ),
        CheckConstraint("duration_seconds > 0", name="duration_seconds_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("attractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    transcript: Mapped[str] = mapped_column(String(4000), nullable=False)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="text_demo",
    )

    attraction: Mapped[Attraction] = relationship(back_populates="narrations")


class RouteNode(Base):
    __tablename__ = "route_nodes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    attraction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("attractions.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    accessible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class RouteEdge(Base):
    __tablename__ = "route_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_node_id",
            "to_node_id",
            name="uq_route_edges_direction",
        ),
        CheckConstraint("from_node_id <> to_node_id", name="different_nodes"),
        CheckConstraint("walk_minutes > 0", name="walk_minutes_positive"),
        CheckConstraint("distance_meters > 0", name="distance_meters_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    from_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    walk_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_meters: Mapped[int] = mapped_column(Integer, nullable=False)
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
    stroller_ok: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    bidirectional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class CrowdSnapshot(Base):
    __tablename__ = "crowd_snapshots"
    __table_args__ = (
        CheckConstraint(
            "occupancy_bps >= 0 AND occupancy_bps <= 10000",
            name="occupancy_bps_range",
        ),
        CheckConstraint("wait_minutes >= 0", name="wait_minutes_nonnegative"),
        CheckConstraint("people_count >= 0", name="people_count_nonnegative"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        Index("ix_crowd_snapshots_attraction_observed", "attraction_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("attractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    crowd_level: Mapped[str] = mapped_column(String(16), nullable=False)
    occupancy_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    people_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Itinerary(Base):
    __tablename__ = "itineraries"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_minutes_positive"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE')", name="valid_status"),
        Index("ix_itineraries_user_visit_date", "user_id", "visit_date"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    interests: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    companion_type: Mapped[str] = mapped_column(String(24), nullable=False)
    fitness_level: Mapped[str] = mapped_column(String(16), nullable=False)
    accessible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="rules")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    explanation: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    unscheduled_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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

    items: Mapped[list[ItineraryItem]] = relationship(
        back_populates="itinerary",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ItineraryItem.ordinal",
    )


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"
    __table_args__ = (
        UniqueConstraint(
            "itinerary_id",
            "ordinal",
            name="uq_itinerary_items_ordinal",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("walk_minutes >= 0", name="walk_minutes_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    itinerary_id: Mapped[UUID] = mapped_column(
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[UUID] = mapped_column(nullable=False)
    attraction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("attractions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    crowd_level: Mapped[str] = mapped_column(String(16), nullable=False)
    walk_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    explanation: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    itinerary: Mapped[Itinerary] = relationship(back_populates="items")


class PlanRun(Base):
    __tablename__ = "plan_runs"
    __table_args__ = (
        UniqueConstraint(
            "itinerary_id",
            "revision",
            name="uq_plan_runs_itinerary_revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    itinerary_id: Mapped[UUID] = mapped_column(
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    run_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="rules")
    inputs: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    score_breakdown: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ConflictCheck(Base):
    __tablename__ = "conflict_checks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    itinerary_id: Mapped[UUID] = mapped_column(
        ForeignKey("itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    has_conflicts: Mapped[bool] = mapped_column(Boolean, nullable=False)
    conflicts: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

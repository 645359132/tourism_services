"""Experience, hospitality, shared inventory, queue, fast-pass, and review models."""

from __future__ import annotations

from datetime import date, datetime
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
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

RESERVATION_HELD = "HELD"
RESERVATION_CONFIRMED = "CONFIRMED"
RESERVATION_COMPLETED = "COMPLETED"
RESERVATION_CANCELLED = "CANCELLED"
RESERVATION_EXPIRED = "EXPIRED"
RESERVATION_NO_SHOW = "NO_SHOW"

QUEUE_WAITING = "WAITING"
QUEUE_CALLED = "CALLED"
QUEUE_SERVING = "SERVING"
QUEUE_LEFT = "LEFT"
QUEUE_COMPLETED = "COMPLETED"
QUEUE_EXPIRED = "EXPIRED"


class Experience(Base):
    __tablename__ = "experiences"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="duration_minutes_positive"),
        CheckConstraint(
            "fastpass_price_cents >= 0",
            name="fastpass_price_nonnegative",
        ),
        CheckConstraint(
            "kind IN ('RIDE', 'SHOW')",
            name="valid_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    min_height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fastpass_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    fastpass_price_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    accessibility: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class ExperienceSession(Base):
    __tablename__ = "experience_sessions"
    __table_args__ = (
        UniqueConstraint(
            "experience_id",
            "starts_at",
            name="uq_experience_sessions_start",
        ),
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED')",
            name="valid_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    experience_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")


class HospitalityVenue(Base):
    __tablename__ = "hospitality_venues"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accessibility: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    amenities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    rating_tenths: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class HospitalityOffer(Base):
    __tablename__ = "hospitality_offers"
    __table_args__ = (
        CheckConstraint("unit_price_cents >= 0", name="price_nonnegative"),
        CheckConstraint("capacity_per_bucket > 0", name="capacity_positive"),
        CheckConstraint("max_party_size > 0", name="party_size_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("hospitality_venues.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity_per_bucket: Mapped[int] = mapped_column(Integer, nullable=False)
    max_party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

    venue: Mapped[HospitalityVenue] = relationship(lazy="joined")
    bundle_components: Mapped[list[BundleComponent]] = relationship(
        back_populates="bundle_offer",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BundleComponent(Base):
    __tablename__ = "bundle_components"
    __table_args__ = (
        UniqueConstraint(
            "bundle_offer_id",
            "component_type",
            "component_resource_id",
            name="uq_bundle_components_resource",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bundle_offer_id: Mapped[UUID] = mapped_column(
        ForeignKey("hospitality_offers.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_type: Mapped[str] = mapped_column(String(32), nullable=False)
    component_resource_id: Mapped[UUID] = mapped_column(nullable=False)
    component_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    bundle_offer: Mapped[HospitalityOffer] = relationship(back_populates="bundle_components")


class InventoryBucket(Base):
    __tablename__ = "inventory_buckets"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "starts_at",
            name="uq_inventory_buckets_resource_start",
        ),
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint("capacity >= 0", name="capacity_nonnegative"),
        CheckConstraint("held >= 0", name="held_nonnegative"),
        CheckConstraint("confirmed >= 0", name="confirmed_nonnegative"),
        CheckConstraint("held + confirmed <= capacity", name="within_capacity"),
        Index("ix_inventory_buckets_business_date", "business_date"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    held: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    confirmed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_reservations_user_id_idempotency_key",
        ),
        CheckConstraint("party_size > 0", name="party_size_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("total_cents >= 0", name="total_nonnegative"),
        CheckConstraint(
            "status IN ('HELD', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'EXPIRED', 'NO_SHOW')",
            name="valid_status",
        ),
        Index("ix_reservations_user_starts", "user_id", "starts_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    booking_no: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_name: Mapped[str] = mapped_column(String(180), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RESERVATION_HELD)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="demo")
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirm_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cancel_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hold_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    allocations: Mapped[list[ReservationAllocation]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ReservationAllocation.business_date",
    )


class ReservationAllocation(Base):
    __tablename__ = "reservation_allocations"
    __table_args__ = (
        UniqueConstraint(
            "reservation_id",
            "bucket_id",
            name="uq_reservation_allocations_bucket",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_buckets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RESERVATION_HELD)

    reservation: Mapped[Reservation] = relationship(back_populates="allocations")


class UserScheduleLock(Base):
    __tablename__ = "user_schedule_locks"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "experience_id",
            "active_key",
            name="uq_queue_entries_active",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_queue_entries_user_id_idempotency_key",
        ),
        CheckConstraint("party_size > 0", name="party_size_positive"),
        CheckConstraint("estimated_wait_minutes >= 0", name="wait_nonnegative"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "status IN ('WAITING', 'CALLED', 'SERVING', 'COMPLETED', 'LEFT', 'EXPIRED')",
            name="valid_status",
        ),
        Index("ix_queue_entries_experience_status", "experience_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    queue_no: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    experience_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
    )
    itinerary_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("itineraries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=QUEUE_WAITING)
    active_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    leave_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    leave_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    join_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    serving_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class QueueCounter(Base):
    __tablename__ = "queue_counters"

    experience_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiences.id", ondelete="CASCADE"),
        primary_key=True,
    )
    next_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class FastPass(Base):
    __tablename__ = "fast_passes"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_fast_passes_user_id_idempotency_key",
        ),
        CheckConstraint("price_cents >= 0", name="price_nonnegative"),
        CheckConstraint(
            "status IN ('ACTIVE', 'USED', 'CANCELLED', 'EXPIRED')",
            name="valid_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    queue_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("queue_entries.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    experience_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiences.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_buckets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="demo")
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payment_reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "reservation_id",
            name="uq_reviews_user_reservation",
        ),
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="PUBLISHED",
        server_default="PUBLISHED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

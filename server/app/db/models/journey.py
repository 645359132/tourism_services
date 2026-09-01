"""Offline travel, emergency, digital passport, and green-task models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
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


class OfflinePack(Base):
    __tablename__ = "offline_packs"
    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > published_at",
            name="expiry_after_publish",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(800), nullable=False)
    etag: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

    assets: Mapped[list[OfflineAsset]] = relationship(
        back_populates="pack",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OfflineAsset.asset_key",
    )


class OfflineAsset(Base):
    __tablename__ = "offline_assets"
    __table_args__ = (
        UniqueConstraint("pack_id", "asset_key", name="uq_offline_assets_key"),
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pack_id: Mapped[UUID] = mapped_column(
        ForeignKey("offline_packs.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_key: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    pack: Mapped[OfflinePack] = relationship(back_populates="assets")


class DeviceSyncState(Base):
    __tablename__ = "device_sync_states"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_device_sync_states_device"),
        CheckConstraint("cursor >= 0", name="cursor_nonnegative"),
        CheckConstraint("last_client_version >= 0", name="client_version_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_client_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class UserSyncCounter(Base):
    __tablename__ = "user_sync_counters"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    next_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class OfflineMutation(Base):
    __tablename__ = "offline_mutations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "device_id",
            "client_mutation_id",
            name="uq_offline_mutations_client_id",
        ),
        UniqueConstraint(
            "user_id",
            "server_cursor",
            name="uq_offline_mutations_server_cursor",
        ),
        CheckConstraint("client_version > 0", name="client_version_positive"),
        CheckConstraint("server_cursor > 0", name="server_cursor_positive"),
        CheckConstraint("operation IN ('UPSERT', 'DELETE')", name="valid_operation"),
        Index("ix_offline_mutations_user_cursor", "user_id", "server_cursor"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    client_mutation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_version: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    server_cursor: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EmergencyResource(Base):
    __tablename__ = "emergency_resources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    instructions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class EmergencyBulletin(Base):
    __tablename__ = "emergency_bulletins"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'CRITICAL')",
            name="valid_severity",
        ),
        CheckConstraint("ends_at > starts_at", name="time_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class SosRequest(Base):
    __tablename__ = "sos_requests"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_sos_requests_user_idempotency_key",
        ),
        CheckConstraint(
            "kind IN ('MEDICAL', 'LOST', 'SAFETY', 'OTHER')",
            name="valid_kind",
        ),
        CheckConstraint(
            "status IN ('DEMO_RECEIVED', 'ACKNOWLEDGED', 'RESOLVED')",
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
        CheckConstraint(
            "(latitude_e6 IS NULL AND longitude_e6 IS NULL) OR "
            "(latitude_e6 IS NOT NULL AND longitude_e6 IS NOT NULL)",
            name="coordinate_pair",
        ),
        Index("ix_sos_requests_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sos_no: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="DEMO_RECEIVED",
    )
    node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    latitude_e6: Mapped[int | None] = mapped_column(Integer, nullable=True)
    longitude_e6: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="demo_sos")
    is_demo: Mapped[bool] = mapped_column(
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
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class PassportStampDefinition(Base):
    __tablename__ = "passport_stamp_definitions"
    __table_args__ = (CheckConstraint("points_award > 0", name="points_positive"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(800), nullable=False)
    node_id: Mapped[UUID] = mapped_column(
        ForeignKey("route_nodes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    points_award: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class PassportStamp(Base):
    __tablename__ = "passport_stamps"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "definition_id",
            name="uq_passport_stamps_user_definition",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_passport_stamps_user_idempotency",
        ),
        CheckConstraint("points_awarded > 0", name="points_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("passport_stamp_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="demo_checkin",
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    definition: Mapped[PassportStampDefinition] = relationship(lazy="joined")


class GreenTask(Base):
    __tablename__ = "green_tasks"
    __table_args__ = (
        CheckConstraint("points_award > 0", name="points_positive"),
        CheckConstraint(
            "kind IN ('TRANSPORT', 'REFILL', 'CULTURE', 'RECYCLE')",
            name="valid_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(800), nullable=False)
    points_award: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_hint: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class GreenTaskCompletion(Base):
    __tablename__ = "green_task_completions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "task_id",
            name="uq_green_task_completions_user_task",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_green_task_completions_user_idempotency",
        ),
        CheckConstraint("points_awarded > 0", name="points_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("green_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence: Mapped[str] = mapped_column(String(500), nullable=False)
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="demo_green_verifier",
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    task: Mapped[GreenTask] = relationship(lazy="joined")


class JourneyIdempotencyReceipt(Base):
    __tablename__ = "journey_idempotency_receipts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "scope",
            "idempotency_key",
            name="uq_journey_idempotency_receipts_key",
        ),
        CheckConstraint(
            "scope IN ('PASSPORT_STAMP', 'GREEN_TASK')",
            name="valid_scope",
        ),
        CheckConstraint(
            "outcome IN ('DUPLICATE_REJECTED')",
            name="valid_outcome",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[UUID] = mapped_column(nullable=False)
    result_id: Mapped[UUID] = mapped_column(nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="DUPLICATE_REJECTED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

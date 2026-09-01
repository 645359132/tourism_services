"""Ticket catalog, inventory ledger, order, credential, and after-sale models."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID, uuid4

from sqlalchemy import (
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

ORDER_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_PAID = "PAID"
ORDER_REFUNDED = "REFUNDED"
ORDER_EXPIRED = "EXPIRED"
ORDER_CANCELLED = "CANCELLED"

TICKET_ISSUED = "ISSUED"
TICKET_USED = "USED"
TICKET_VOID = "VOID"


class TicketType(Base):
    __tablename__ = "ticket_types"
    __table_args__ = (
        CheckConstraint("base_price_cents >= 0", name="base_price_nonnegative"),
        CheckConstraint("admission_count > 0", name="admission_count_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    audience: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    base_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    admission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    slots: Mapped[list[TicketSlot]] = relationship(back_populates="ticket_type")


class TicketSlot(Base):
    __tablename__ = "ticket_slots"
    __table_args__ = (
        UniqueConstraint(
            "ticket_type_id",
            "visit_date",
            "start_time",
            "end_time",
            name="uq_ticket_slots_schedule",
        ),
        CheckConstraint("end_time > start_time", name="slot_time_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    visit_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )

    ticket_type: Mapped[TicketType] = relationship(back_populates="slots", lazy="joined")
    inventory: Mapped[TicketInventory] = relationship(
        back_populates="slot",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="joined",
    )


class TicketInventory(Base):
    __tablename__ = "ticket_inventories"
    __table_args__ = (
        CheckConstraint("capacity >= 0", name="capacity_nonnegative"),
        CheckConstraint("reserved >= 0", name="reserved_nonnegative"),
        CheckConstraint("sold >= 0", name="sold_nonnegative"),
        CheckConstraint("reserved + sold <= capacity", name="inventory_within_capacity"),
    )

    slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_slots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    slot: Mapped[TicketSlot] = relationship(back_populates="inventory")


class DynamicPriceRule(Base):
    __tablename__ = "dynamic_price_rules"
    __table_args__ = (
        CheckConstraint("adjustment_bps > -10000", name="valid_adjustment_bps"),
        CheckConstraint(
            "min_occupancy_bps IS NULL OR (min_occupancy_bps >= 0 AND min_occupancy_bps <= 10000)",
            name="valid_min_occupancy_bps",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    ticket_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ticket_types.id", ondelete="CASCADE"),
        nullable=True,
    )
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    adjustment_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    weekend_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    min_occupancy_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )


class TicketOrder(Base):
    __tablename__ = "ticket_orders"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_ticket_orders_user_id_idempotency_key",
        ),
        CheckConstraint("total_cents >= 0", name="total_nonnegative"),
        CheckConstraint(
            "status IN ('PENDING_PAYMENT', 'PAID', 'REFUNDED', 'EXPIRED', 'CANCELLED')",
            name="valid_order_status",
        ),
        Index("ix_ticket_orders_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ORDER_PENDING_PAYMENT,
    )
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payment_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    items: Mapped[list[TicketOrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tickets: Mapped[list[ElectronicTicket]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TicketOrderItem(Base):
    __tablename__ = "ticket_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_cents >= 0", name="unit_price_nonnegative"),
        CheckConstraint("line_total_cents >= 0", name="line_total_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ticket_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ticket_type_name: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[TicketOrder] = relationship(back_populates="items")
    slot: Mapped[TicketSlot] = relationship(lazy="joined")


class ElectronicTicket(Base):
    __tablename__ = "electronic_tickets"
    __table_args__ = (
        Index("ix_electronic_tickets_order_status", "order_id", "status"),
        CheckConstraint(
            "status IN ('ISSUED', 'USED', 'VOID')",
            name="valid_ticket_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TICKET_ISSUED)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    order: Mapped[TicketOrder] = relationship(back_populates="tickets")
    slot: Mapped[TicketSlot] = relationship(lazy="joined")


class TicketValidation(Base):
    __tablename__ = "ticket_validations"
    __table_args__ = (CheckConstraint("result IN ('ACCEPTED')", name="valid_validation_result"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ticket_id: Mapped[UUID] = mapped_column(
        ForeignKey("electronic_tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    validator_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_refund_requests_user_id_idempotency_key",
        ),
        CheckConstraint(
            "status IN ('SUCCEEDED', 'REJECTED')",
            name="valid_refund_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RescheduleRequest(Base):
    __tablename__ = "reschedule_requests"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_reschedule_requests_user_id_idempotency_key",
        ),
        CheckConstraint(
            "status IN ('SUCCEEDED', 'REJECTED')",
            name="valid_reschedule_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("ticket_slots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

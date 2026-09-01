"""Add the complete ticketing inventory and order slice.

Revision ID: 20260901_0003
Revises: 20260901_0002
Create Date: 2026-09-01 00:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0003"
down_revision: str | None = "20260901_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("audience", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("base_price_cents", sa.Integer(), nullable=False),
        sa.Column("admission_count", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "admission_count > 0",
            name=op.f("ck_ticket_types_admission_count_positive"),
        ),
        sa.CheckConstraint(
            "base_price_cents >= 0",
            name=op.f("ck_ticket_types_base_price_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_types")),
        sa.UniqueConstraint("code", name=op.f("uq_ticket_types_code")),
    )
    op.create_table(
        "ticket_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_type_id", sa.Uuid(), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "end_time > start_time",
            name=op.f("ck_ticket_slots_slot_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_type_id"],
            ["ticket_types.id"],
            name=op.f("fk_ticket_slots_ticket_type_id_ticket_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_slots")),
        sa.UniqueConstraint(
            "ticket_type_id",
            "visit_date",
            "start_time",
            "end_time",
            name="uq_ticket_slots_schedule",
        ),
    )
    op.create_index(
        op.f("ix_ticket_slots_visit_date"),
        "ticket_slots",
        ["visit_date"],
        unique=False,
    )
    op.create_table(
        "dynamic_price_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("ticket_type_id", sa.Uuid(), nullable=True),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("adjustment_bps", sa.Integer(), nullable=False),
        sa.Column("weekend_only", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("min_occupancy_bps", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "adjustment_bps > -10000",
            name=op.f("ck_dynamic_price_rules_valid_adjustment_bps"),
        ),
        sa.CheckConstraint(
            "min_occupancy_bps IS NULL OR (min_occupancy_bps >= 0 AND min_occupancy_bps <= 10000)",
            name=op.f("ck_dynamic_price_rules_valid_min_occupancy_bps"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_type_id"],
            ["ticket_types.id"],
            name=op.f("fk_dynamic_price_rules_ticket_type_id_ticket_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dynamic_price_rules")),
        sa.UniqueConstraint("name", name=op.f("uq_dynamic_price_rules_name")),
    )
    op.create_table(
        "ticket_inventories",
        sa.Column("slot_id", sa.Uuid(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sold", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "capacity >= 0",
            name=op.f("ck_ticket_inventories_capacity_nonnegative"),
        ),
        sa.CheckConstraint(
            "reserved + sold <= capacity",
            name=op.f("ck_ticket_inventories_inventory_within_capacity"),
        ),
        sa.CheckConstraint(
            "reserved >= 0",
            name=op.f("ck_ticket_inventories_reserved_nonnegative"),
        ),
        sa.CheckConstraint(
            "sold >= 0",
            name=op.f("ck_ticket_inventories_sold_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"],
            ["ticket_slots.id"],
            name=op.f("fk_ticket_inventories_slot_id_ticket_slots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("slot_id", name=op.f("pk_ticket_inventories")),
    )
    op.create_table(
        "ticket_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_no", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("payment_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("payment_request_hash", sa.String(length=64), nullable=True),
        sa.Column("payment_reference", sa.String(length=100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING_PAYMENT', 'PAID', 'REFUNDED', 'EXPIRED', 'CANCELLED')",
            name=op.f("ck_ticket_orders_valid_order_status"),
        ),
        sa.CheckConstraint(
            "total_cents >= 0",
            name=op.f("ck_ticket_orders_total_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_ticket_orders_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_orders")),
        sa.UniqueConstraint("order_no", name=op.f("uq_ticket_orders_order_no")),
        sa.UniqueConstraint(
            "payment_reference",
            name=op.f("uq_ticket_orders_payment_reference"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_ticket_orders_user_id_idempotency_key",
        ),
    )
    op.create_index(
        "ix_ticket_orders_user_created",
        "ticket_orders",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "ticket_order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("slot_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_type_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_type_name", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("line_total_cents", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "line_total_cents >= 0",
            name=op.f("ck_ticket_order_items_line_total_nonnegative"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_ticket_order_items_quantity_positive"),
        ),
        sa.CheckConstraint(
            "unit_price_cents >= 0",
            name=op.f("ck_ticket_order_items_unit_price_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["ticket_orders.id"],
            name=op.f("fk_ticket_order_items_order_id_ticket_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"],
            ["ticket_slots.id"],
            name=op.f("fk_ticket_order_items_slot_id_ticket_slots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_type_id"],
            ["ticket_types.id"],
            name=op.f("fk_ticket_order_items_ticket_type_id_ticket_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_order_items")),
    )
    op.create_table(
        "electronic_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("slot_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_code", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "status IN ('ISSUED', 'USED', 'VOID')",
            name=op.f("ck_electronic_tickets_valid_ticket_status"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["ticket_orders.id"],
            name=op.f("fk_electronic_tickets_order_id_ticket_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["ticket_order_items.id"],
            name=op.f("fk_electronic_tickets_order_item_id_ticket_order_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["slot_id"],
            ["ticket_slots.id"],
            name=op.f("fk_electronic_tickets_slot_id_ticket_slots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_electronic_tickets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_electronic_tickets")),
        sa.UniqueConstraint(
            "ticket_code",
            name=op.f("uq_electronic_tickets_ticket_code"),
        ),
    )
    op.create_index(
        "ix_electronic_tickets_order_status",
        "electronic_tickets",
        ["order_id", "status"],
        unique=False,
    )
    op.create_table(
        "refund_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'REJECTED')",
            name=op.f("ck_refund_requests_valid_refund_status"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["ticket_orders.id"],
            name=op.f("fk_refund_requests_order_id_ticket_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refund_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refund_requests")),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_refund_requests_user_id_idempotency_key",
        ),
    )
    op.create_table(
        "reschedule_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("source_slot_id", sa.Uuid(), nullable=False),
        sa.Column("target_slot_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'REJECTED')",
            name=op.f("ck_reschedule_requests_valid_reschedule_status"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["ticket_orders.id"],
            name=op.f("fk_reschedule_requests_order_id_ticket_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_slot_id"],
            ["ticket_slots.id"],
            name=op.f("fk_reschedule_requests_source_slot_id_ticket_slots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_slot_id"],
            ["ticket_slots.id"],
            name=op.f("fk_reschedule_requests_target_slot_id_ticket_slots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reschedule_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reschedule_requests")),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_reschedule_requests_user_id_idempotency_key",
        ),
    )
    op.create_table(
        "ticket_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("validator_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("gate_code", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column(
            "validated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('ACCEPTED')",
            name=op.f("ck_ticket_validations_valid_validation_result"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["electronic_tickets.id"],
            name=op.f("fk_ticket_validations_ticket_id_electronic_tickets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["validator_user_id"],
            ["users.id"],
            name=op.f("fk_ticket_validations_validator_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_validations")),
        sa.UniqueConstraint(
            "request_id",
            name=op.f("uq_ticket_validations_request_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("ticket_validations")
    op.drop_table("reschedule_requests")
    op.drop_table("refund_requests")
    op.drop_index("ix_electronic_tickets_order_status", table_name="electronic_tickets")
    op.drop_table("electronic_tickets")
    op.drop_table("ticket_order_items")
    op.drop_index("ix_ticket_orders_user_created", table_name="ticket_orders")
    op.drop_table("ticket_orders")
    op.drop_table("ticket_inventories")
    op.drop_table("dynamic_price_rules")
    op.drop_index(op.f("ix_ticket_slots_visit_date"), table_name="ticket_slots")
    op.drop_table("ticket_slots")
    op.drop_table("ticket_types")

"""Add experiences, hospitality, shared reservations, queues, fast passes, and reviews.

Revision ID: 20260901_0005
Revises: 20260901_0004
Create Date: 2026-09-01 00:40:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0005"
down_revision: str | None = "20260901_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("min_height_cm", sa.Integer(), nullable=True),
        sa.Column("fastpass_allowed", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("fastpass_price_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accessibility", sa.JSON(), nullable=False),
        sa.Column("wait_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "duration_minutes > 0",
            name=op.f("ck_experiences_duration_minutes_positive"),
        ),
        sa.CheckConstraint(
            "fastpass_price_cents >= 0",
            name=op.f("ck_experiences_fastpass_price_nonnegative"),
        ),
        sa.CheckConstraint(
            "kind IN ('RIDE', 'SHOW')",
            name=op.f("ck_experiences_valid_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["route_nodes.id"],
            name=op.f("fk_experiences_node_id_route_nodes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiences")),
        sa.UniqueConstraint("code", name=op.f("uq_experiences_code")),
    )
    op.create_table(
        "hospitality_venues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("accessibility", sa.JSON(), nullable=False),
        sa.Column("amenities", sa.JSON(), nullable=False),
        sa.Column("rating_tenths", sa.Integer(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["route_nodes.id"],
            name=op.f("fk_hospitality_venues_node_id_route_nodes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospitality_venues")),
        sa.UniqueConstraint("code", name=op.f("uq_hospitality_venues_code")),
    )
    op.create_table(
        "experience_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experience_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name=op.f("ck_experience_sessions_time_order"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'CANCELLED')",
            name=op.f("ck_experience_sessions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["experiences.id"],
            name=op.f("fk_experience_sessions_experience_id_experiences"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experience_sessions")),
        sa.UniqueConstraint(
            "experience_id",
            "starts_at",
            name="uq_experience_sessions_start",
        ),
    )
    op.create_table(
        "hospitality_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("capacity_per_bucket", sa.Integer(), nullable=False),
        sa.Column("max_party_size", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "capacity_per_bucket > 0",
            name=op.f("ck_hospitality_offers_capacity_positive"),
        ),
        sa.CheckConstraint(
            "max_party_size > 0",
            name=op.f("ck_hospitality_offers_party_size_positive"),
        ),
        sa.CheckConstraint(
            "unit_price_cents >= 0",
            name=op.f("ck_hospitality_offers_price_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["hospitality_venues.id"],
            name=op.f("fk_hospitality_offers_venue_id_hospitality_venues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospitality_offers")),
        sa.UniqueConstraint("code", name=op.f("uq_hospitality_offers_code")),
    )
    op.create_table(
        "inventory_buckets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("held", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confirmed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "capacity >= 0",
            name=op.f("ck_inventory_buckets_capacity_nonnegative"),
        ),
        sa.CheckConstraint(
            "confirmed >= 0",
            name=op.f("ck_inventory_buckets_confirmed_nonnegative"),
        ),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name=op.f("ck_inventory_buckets_time_order"),
        ),
        sa.CheckConstraint(
            "held >= 0",
            name=op.f("ck_inventory_buckets_held_nonnegative"),
        ),
        sa.CheckConstraint(
            "held + confirmed <= capacity",
            name=op.f("ck_inventory_buckets_within_capacity"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_buckets")),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "starts_at",
            name="uq_inventory_buckets_resource_start",
        ),
    )
    op.create_index(
        "ix_inventory_buckets_business_date",
        "inventory_buckets",
        ["business_date"],
        unique=False,
    )
    op.create_table(
        "user_schedule_locks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_schedule_locks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_schedule_locks")),
    )
    op.create_table(
        "bundle_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bundle_offer_id", sa.Uuid(), nullable=False),
        sa.Column("component_type", sa.String(length=32), nullable=False),
        sa.Column("component_resource_id", sa.Uuid(), nullable=False),
        sa.Column("component_name", sa.String(length=160), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_bundle_components_quantity_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["bundle_offer_id"],
            ["hospitality_offers.id"],
            name=op.f("fk_bundle_components_bundle_offer_id_hospitality_offers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bundle_components")),
        sa.UniqueConstraint(
            "bundle_offer_id",
            "component_type",
            "component_resource_id",
            name="uq_bundle_components_resource",
        ),
    )
    op.create_table(
        "queue_counters",
        sa.Column("experience_id", sa.Uuid(), nullable=False),
        sa.Column("next_sequence", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["experiences.id"],
            name=op.f("fk_queue_counters_experience_id_experiences"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("experience_id", name=op.f("pk_queue_counters")),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booking_no", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("resource_name", sa.String(length=180), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("confirm_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("confirm_request_hash", sa.String(length=64), nullable=True),
        sa.Column("cancel_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("cancel_request_hash", sa.String(length=64), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "party_size > 0",
            name=op.f("ck_reservations_party_size_positive"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_reservations_quantity_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('HELD', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'EXPIRED', 'NO_SHOW')",
            name=op.f("ck_reservations_valid_status"),
        ),
        sa.CheckConstraint(
            "total_cents >= 0",
            name=op.f("ck_reservations_total_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reservations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("booking_no", name=op.f("uq_reservations_booking_no")),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_reservations_user_id_idempotency_key",
        ),
    )
    op.create_index(
        "ix_reservations_user_starts",
        "reservations",
        ["user_id", "starts_at"],
        unique=False,
    )
    op.create_table(
        "queue_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("queue_no", sa.String(length=48), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("experience_id", sa.Uuid(), nullable=False),
        sa.Column("itinerary_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("active_key", sa.String(length=16), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("leave_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("leave_request_hash", sa.String(length=64), nullable=True),
        sa.Column("estimated_wait_minutes", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), server_default="1", nullable=False),
        sa.Column("join_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("serving_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "estimated_wait_minutes >= 0",
            name=op.f("ck_queue_entries_wait_nonnegative"),
        ),
        sa.CheckConstraint(
            "party_size > 0",
            name=op.f("ck_queue_entries_party_size_positive"),
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_queue_entries_sequence_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('WAITING', 'CALLED', 'SERVING', 'COMPLETED', 'LEFT', 'EXPIRED')",
            name=op.f("ck_queue_entries_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["experiences.id"],
            name=op.f("fk_queue_entries_experience_id_experiences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["itinerary_id"],
            ["itineraries.id"],
            name=op.f("fk_queue_entries_itinerary_id_itineraries"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_queue_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_queue_entries")),
        sa.UniqueConstraint("queue_no", name=op.f("uq_queue_entries_queue_no")),
        sa.UniqueConstraint(
            "user_id",
            "experience_id",
            "active_key",
            name="uq_queue_entries_active",
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_queue_entries_user_id_idempotency_key",
        ),
    )
    op.create_index(
        "ix_queue_entries_experience_status",
        "queue_entries",
        ["experience_id", "status"],
        unique=False,
    )
    op.create_table(
        "reservation_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("bucket_id", sa.Uuid(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_reservation_allocations_quantity_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["bucket_id"],
            ["inventory_buckets.id"],
            name=op.f("fk_reservation_allocations_bucket_id_inventory_buckets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.id"],
            name=op.f("fk_reservation_allocations_reservation_id_reservations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservation_allocations")),
        sa.UniqueConstraint(
            "reservation_id",
            "bucket_id",
            name="uq_reservation_allocations_bucket",
        ),
    )
    op.create_table(
        "fast_passes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=48), nullable=False),
        sa.Column("queue_entry_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("experience_id", sa.Uuid(), nullable=False),
        sa.Column("bucket_id", sa.Uuid(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payment_reference", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "price_cents >= 0",
            name=op.f("ck_fast_passes_price_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'USED', 'CANCELLED', 'EXPIRED')",
            name=op.f("ck_fast_passes_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["bucket_id"],
            ["inventory_buckets.id"],
            name=op.f("fk_fast_passes_bucket_id_inventory_buckets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["experience_id"],
            ["experiences.id"],
            name=op.f("fk_fast_passes_experience_id_experiences"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["queue_entry_id"],
            ["queue_entries.id"],
            name=op.f("fk_fast_passes_queue_entry_id_queue_entries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_fast_passes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fast_passes")),
        sa.UniqueConstraint("code", name=op.f("uq_fast_passes_code")),
        sa.UniqueConstraint(
            "payment_reference",
            name=op.f("uq_fast_passes_payment_reference"),
        ),
        sa.UniqueConstraint(
            "queue_entry_id",
            name=op.f("uq_fast_passes_queue_entry_id"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_fast_passes_user_id_idempotency_key",
        ),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="PUBLISHED", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name=op.f("ck_reviews_rating_range"),
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.id"],
            name=op.f("fk_reviews_reservation_id_reservations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reviews_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint(
            "user_id",
            "reservation_id",
            name="uq_reviews_user_reservation",
        ),
    )


def downgrade() -> None:
    op.drop_table("reviews")
    op.drop_table("fast_passes")
    op.drop_table("reservation_allocations")
    op.drop_index("ix_queue_entries_experience_status", table_name="queue_entries")
    op.drop_table("queue_entries")
    op.drop_index("ix_reservations_user_starts", table_name="reservations")
    op.drop_table("reservations")
    op.drop_table("queue_counters")
    op.drop_table("bundle_components")
    op.drop_table("user_schedule_locks")
    op.drop_index("ix_inventory_buckets_business_date", table_name="inventory_buckets")
    op.drop_table("inventory_buckets")
    op.drop_table("hospitality_offers")
    op.drop_table("experience_sessions")
    op.drop_table("hospitality_venues")
    op.drop_table("experiences")

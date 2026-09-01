"""Add schematic guide, simulated crowd, and rule-planned itineraries.

Revision ID: 20260901_0004
Revises: 20260901_0003
Create Date: 2026-09-01 00:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0004"
down_revision: str | None = "20260901_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("visit_minutes", sa.Integer(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("accessibility", sa.JSON(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "visit_minutes > 0",
            name=op.f("ck_attractions_visit_minutes_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attractions")),
        sa.UniqueConstraint("code", name=op.f("uq_attractions_code")),
    )
    op.create_table(
        "itineraries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("interests", sa.JSON(), nullable=False),
        sa.Column("companion_type", sa.String(length=24), nullable=False),
        sa.Column("fitness_level", sa.String(length=16), nullable=False),
        sa.Column("accessible", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("unscheduled_reasons", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_minutes > 0",
            name=op.f("ck_itineraries_duration_minutes_positive"),
        ),
        sa.CheckConstraint(
            "revision > 0",
            name=op.f("ck_itineraries_revision_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE')",
            name=op.f("ck_itineraries_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_itineraries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_itineraries")),
    )
    op.create_index(
        "ix_itineraries_user_visit_date",
        "itineraries",
        ["user_id", "visit_date"],
        unique=False,
    )
    op.create_table(
        "narrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attraction_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("transcript", sa.String(length=4000), nullable=False),
        sa.Column("audio_url", sa.String(length=500), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("provider_mode", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "duration_seconds > 0",
            name=op.f("ck_narrations_duration_seconds_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["attraction_id"],
            ["attractions.id"],
            name=op.f("fk_narrations_attraction_id_attractions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_narrations")),
        sa.UniqueConstraint(
            "attraction_id",
            "language",
            name="uq_narrations_attraction_language",
        ),
    )
    op.create_table(
        "route_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("attraction_id", sa.Uuid(), nullable=True),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.Column("accessible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attraction_id"],
            ["attractions.id"],
            name=op.f("fk_route_nodes_attraction_id_attractions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_nodes")),
        sa.UniqueConstraint(
            "attraction_id",
            name=op.f("uq_route_nodes_attraction_id"),
        ),
        sa.UniqueConstraint("code", name=op.f("uq_route_nodes_code")),
    )
    op.create_table(
        "crowd_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attraction_id", sa.Uuid(), nullable=False),
        sa.Column("crowd_level", sa.String(length=16), nullable=False),
        sa.Column("occupancy_bps", sa.Integer(), nullable=False),
        sa.Column("wait_minutes", sa.Integer(), nullable=False),
        sa.Column("people_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "people_count >= 0",
            name=op.f("ck_crowd_snapshots_people_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "occupancy_bps >= 0 AND occupancy_bps <= 10000",
            name=op.f("ck_crowd_snapshots_occupancy_bps_range"),
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_crowd_snapshots_sequence_positive"),
        ),
        sa.CheckConstraint(
            "wait_minutes >= 0",
            name=op.f("ck_crowd_snapshots_wait_minutes_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["attraction_id"],
            ["attractions.id"],
            name=op.f("fk_crowd_snapshots_attraction_id_attractions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crowd_snapshots")),
    )
    op.create_index(
        "ix_crowd_snapshots_attraction_observed",
        "crowd_snapshots",
        ["attraction_id", "observed_at"],
        unique=False,
    )
    op.create_table(
        "route_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_node_id", sa.Uuid(), nullable=False),
        sa.Column("to_node_id", sa.Uuid(), nullable=False),
        sa.Column("walk_minutes", sa.Integer(), nullable=False),
        sa.Column("distance_meters", sa.Integer(), nullable=False),
        sa.Column("accessible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("wheelchair_ok", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("stroller_ok", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("bidirectional", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "from_node_id <> to_node_id",
            name=op.f("ck_route_edges_different_nodes"),
        ),
        sa.CheckConstraint(
            "distance_meters > 0",
            name=op.f("ck_route_edges_distance_meters_positive"),
        ),
        sa.CheckConstraint(
            "walk_minutes > 0",
            name=op.f("ck_route_edges_walk_minutes_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["from_node_id"],
            ["route_nodes.id"],
            name=op.f("fk_route_edges_from_node_id_route_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_node_id"],
            ["route_nodes.id"],
            name=op.f("fk_route_edges_to_node_id_route_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_edges")),
        sa.UniqueConstraint(
            "from_node_id",
            "to_node_id",
            name="uq_route_edges_direction",
        ),
    )
    op.create_table(
        "itinerary_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("itinerary_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("attraction_id", sa.Uuid(), nullable=True),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("crowd_level", sa.String(length=16), nullable=False),
        sa.Column("walk_minutes", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "end_at > start_at",
            name=op.f("ck_itinerary_items_time_order"),
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_itinerary_items_ordinal_positive"),
        ),
        sa.CheckConstraint(
            "walk_minutes >= 0",
            name=op.f("ck_itinerary_items_walk_minutes_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["itinerary_id"],
            ["itineraries.id"],
            name=op.f("fk_itinerary_items_itinerary_id_itineraries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attraction_id"],
            ["attractions.id"],
            name=op.f("fk_itinerary_items_attraction_id_attractions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["route_nodes.id"],
            name=op.f("fk_itinerary_items_node_id_route_nodes"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_itinerary_items")),
        sa.UniqueConstraint(
            "itinerary_id",
            "ordinal",
            name="uq_itinerary_items_ordinal",
        ),
    )
    op.create_table(
        "plan_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("itinerary_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["itinerary_id"],
            ["itineraries.id"],
            name=op.f("fk_plan_runs_itinerary_id_itineraries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_runs")),
        sa.UniqueConstraint(
            "itinerary_id",
            "revision",
            name="uq_plan_runs_itinerary_revision",
        ),
    )
    op.create_table(
        "conflict_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("itinerary_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("has_conflicts", sa.Boolean(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["itinerary_id"],
            ["itineraries.id"],
            name=op.f("fk_conflict_checks_itinerary_id_itineraries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_conflict_checks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflict_checks")),
    )


def downgrade() -> None:
    op.drop_table("conflict_checks")
    op.drop_table("plan_runs")
    op.drop_table("itinerary_items")
    op.drop_table("route_edges")
    op.drop_index(
        "ix_crowd_snapshots_attraction_observed",
        table_name="crowd_snapshots",
    )
    op.drop_table("crowd_snapshots")
    op.drop_table("route_nodes")
    op.drop_table("narrations")
    op.drop_index("ix_itineraries_user_visit_date", table_name="itineraries")
    op.drop_table("itineraries")
    op.drop_table("attractions")

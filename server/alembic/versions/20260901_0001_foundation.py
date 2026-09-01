"""Create foundation seed tracking.

Revision ID: 20260901_0001
Revises:
Create Date: 2026-09-01 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seed_records",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_seed_records")),
    )


def downgrade() -> None:
    op.drop_table("seed_records")

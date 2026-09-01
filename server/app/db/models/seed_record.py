"""Infrastructure-only record of idempotent seed operations."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SeedRecord(Base):
    """Track an applied seed without introducing business-domain tables."""

    __tablename__ = "seed_records"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

"""Tourist-owned personalization settings."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User


class TouristPreference(Base):
    """One-to-one preference record whose owner comes from authentication."""

    __tablename__ = "tourist_preferences"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    preferred_language: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        default="zh-CN",
    )
    interests: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    accessibility_needs: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )
    notifications_enabled: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        default=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="preference")

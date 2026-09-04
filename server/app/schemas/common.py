"""Shared API response metadata."""

from pydantic import BaseModel, Field


class PaginatedResponse(BaseModel):
    """Backward-compatible metadata mixed into bounded list responses."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    total: int = Field(default=0, ge=0)

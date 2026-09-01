"""Current-user preference contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.preference import TouristPreference


class PreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_language: str | None = Field(default=None, min_length=2, max_length=16)
    interests: list[str] | None = Field(default=None, max_length=20)
    accessibility_needs: list[str] | None = Field(default=None, max_length=20)
    notifications_enabled: bool | None = None

    @field_validator("interests", "accessibility_needs")
    @classmethod
    def clean_string_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        if any(len(item) > 64 for item in cleaned):
            raise ValueError("preference values must not exceed 64 characters")
        return list(dict.fromkeys(cleaned))


class PreferenceResponse(BaseModel):
    user_id: str
    preferred_language: str | None
    interests: list[str] | None
    accessibility_needs: list[str] | None
    notifications_enabled: bool | None

    @classmethod
    def from_preference(cls, preference: TouristPreference) -> PreferenceResponse:
        return cls(
            user_id=str(preference.user_id),
            preferred_language=preference.preferred_language,
            interests=preference.interests,
            accessibility_needs=preference.accessibility_needs,
            notifications_enabled=preference.notifications_enabled,
        )

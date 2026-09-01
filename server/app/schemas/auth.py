"""Authentication API contracts shared with the client."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.user import User


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=4096)


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    roles: list[str]

    @classmethod
    def from_user(cls, user: User) -> UserResponse:
        return cls(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            roles=user.role_names,
        )


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

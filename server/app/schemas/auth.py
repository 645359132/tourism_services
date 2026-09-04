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


class RegisterRequest(BaseModel):
    """Public tourist-registration input; authorization is server assigned."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        has_ascii_letter = any(
            "a" <= character <= "z" or "A" <= character <= "Z" for character in value
        )
        has_ascii_digit = any("0" <= character <= "9" for character in value)
        if not has_ascii_letter or not has_ascii_digit:
            raise ValueError("password must contain at least one ASCII letter and one digit")
        return value


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

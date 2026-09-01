"""Environment-driven application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Smart Tourism Service"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_version: str = "0.1.0"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./data/tourism.db"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    cors_allow_credentials: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False
    jwt_secret_key: str = "development-only-jwt-secret-key-change-me-32"
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    jwt_refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    jwt_issuer: str = "smart-tourism-service"
    jwt_audience: str = "smart-tourism-client"
    enable_demo_accounts: bool = False
    ticket_order_reservation_minutes: int = Field(default=15, ge=1, le=120)
    ticket_quote_ttl_seconds: int = Field(default=300, ge=30, le=1800)
    ticket_qr_ttl_seconds: int = Field(default=300, ge=30, le=900)
    ticket_refund_cutoff_hours: int = Field(default=24, ge=0, le=168)
    crowd_publish_interval_seconds: float = Field(default=30.0, ge=0.1, le=3600)

    @field_validator("database_url", mode="before")
    @classmethod
    def use_async_postgres_driver(cls, value: Any) -> Any:
        """Accept common PostgreSQL URLs while consistently using asyncpg."""

        if not isinstance(value, str):
            return value
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        """Accept either a JSON list or a comma-separated environment value."""

        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS JSON value must be a list")
            return parsed
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]

    @model_validator(mode="after")
    def reject_insecure_production_jwt_secret(self) -> Settings:
        """Fail production startup when a development or placeholder key is used."""

        if self.app_env != "production":
            return self

        if self.enable_demo_accounts:
            raise ValueError("Demo accounts must never be enabled in production")

        normalized = self.jwt_secret_key.strip().lower()
        insecure_markers = ("development", "placeholder", "replace", "change-me")
        if len(self.jwt_secret_key.encode("utf-8")) < 32 or any(
            marker in normalized for marker in insecure_markers
        ):
            raise ValueError(
                "Production JWT_SECRET_KEY must be a non-placeholder secret of at least 32 bytes"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()

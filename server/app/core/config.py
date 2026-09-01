"""Environment-driven application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
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


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()

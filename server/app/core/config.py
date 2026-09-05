"""Environment-driven application configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from ipaddress import ip_network
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
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    cors_allow_credentials: bool = True
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    trusted_proxy_networks: Annotated[list[str], NoDecode] = Field(default_factory=list)
    security_headers_enabled: bool = True
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
    ticket_refund_cutoff_hours: int = Field(default=2, ge=0, le=168)
    crowd_publish_interval_seconds: float = Field(default=30.0, ge=0.1, le=3600)
    reservation_hold_minutes: int = Field(default=15, ge=1, le=120)
    reservation_walking_buffer_minutes: int = Field(default=10, ge=0, le=120)
    queue_publish_interval_seconds: float = Field(default=15.0, ge=0.1, le=3600)
    ws_ticket_ttl_seconds: int = Field(default=60, ge=10, le=300)
    fastpass_valid_minutes: int = Field(default=60, ge=5, le=240)
    shop_order_reservation_minutes: int = Field(default=15, ge=1, le=120)
    redis_url: str | None = None
    redis_coordination_enabled: bool = False
    redis_required: bool = False
    redis_key_prefix: str = "tourism"
    redis_socket_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30)
    redis_cache_enabled: bool = True
    redis_pubsub_enabled: bool = True
    redis_rate_limit_enabled: bool = True
    redis_ticket_enabled: bool = True
    redis_lock_enabled: bool = True
    reference_cache_ttl_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_mutation_requests: int = Field(default=120, ge=1, le=10000)
    rate_limit_auth_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_ws_ticket_requests: int = Field(default=30, ge=1, le=10000)
    coordination_claim_ttl_seconds: int = Field(default=30, ge=1, le=300)
    coordination_lock_wait_seconds: float = Field(default=2.0, ge=0, le=30)

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

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError("TRUSTED_HOSTS JSON value must be a list")
            return parsed
        return [host.strip() for host in stripped.split(",") if host.strip()]

    @field_validator("trusted_proxy_networks", mode="before")
    @classmethod
    def parse_trusted_proxy_networks(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError("TRUSTED_PROXY_NETWORKS JSON value must be a list")
            return parsed
        return [network.strip() for network in stripped.split(",") if network.strip()]

    @field_validator("trusted_proxy_networks")
    @classmethod
    def validate_trusted_proxy_networks(cls, value: list[str]) -> list[str]:
        try:
            return [str(ip_network(network, strict=False)) for network in value]
        except ValueError as exc:
            raise ValueError("TRUSTED_PROXY_NETWORKS entries must be IP networks") from exc

    @field_validator("redis_key_prefix")
    @classmethod
    def normalize_redis_key_prefix(cls, value: str) -> str:
        normalized = value.strip().strip(":")
        if not normalized:
            raise ValueError("REDIS_KEY_PREFIX must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> Settings:
        """Reject incomplete coordination and insecure production settings."""

        if self.redis_coordination_enabled and not self.redis_url:
            raise ValueError("REDIS_COORDINATION_ENABLED requires REDIS_URL")
        if self.redis_required and not self.redis_coordination_enabled:
            raise ValueError("REDIS_REQUIRED needs enabled Redis coordination and REDIS_URL")
        if self.app_env != "production":
            return self

        if self.debug:
            raise ValueError("Production DEBUG must be disabled")
        if self.enable_demo_accounts:
            raise ValueError("Demo accounts must never be enabled in production")
        if not self.cors_origins or "*" in self.cors_origins:
            raise ValueError("Production CORS_ORIGINS must be explicit")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            raise ValueError("Production CORS_ORIGINS must use HTTPS")
        if not self.trusted_hosts or "*" in self.trusted_hosts:
            raise ValueError("Production TRUSTED_HOSTS must be explicit")
        if not self.security_headers_enabled:
            raise ValueError("Production security headers must be enabled")

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

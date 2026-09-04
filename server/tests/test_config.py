"""Settings parsing tests."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_postgres_url_uses_async_driver() -> None:
    settings = Settings(database_url="postgresql://user:pass@db:5432/tourism")

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/tourism"


def test_cors_origins_accept_comma_separated_value() -> None:
    settings = Settings(cors_origins="https://one.example, https://two.example")

    assert settings.cors_origins == ["https://one.example", "https://two.example"]


def test_production_rejects_development_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="Production JWT_SECRET_KEY"):
        Settings(
            app_env="production",
            enable_demo_accounts=False,
            jwt_secret_key="development-only-jwt-secret-key-change-me-32",
            cors_origins=["https://client.example"],
            trusted_hosts=["api.example"],
        )


def test_production_rejects_demo_accounts_even_with_strong_secret() -> None:
    with pytest.raises(ValidationError, match="Demo accounts"):
        Settings(
            app_env="production",
            jwt_secret_key="7c96be81bb8a4eb585409088de919e66",
            enable_demo_accounts=True,
            cors_origins=["https://client.example"],
            trusted_hosts=["api.example"],
        )


def test_production_accepts_non_placeholder_secret() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="7c96be81bb8a4eb585409088de919e66",
        enable_demo_accounts=False,
        cors_origins=["https://client.example"],
        trusted_hosts=["api.example"],
    )

    assert settings.app_env == "production"


def test_redis_coordination_requires_a_url() -> None:
    with pytest.raises(ValidationError, match="requires REDIS_URL"):
        Settings(redis_coordination_enabled=True)


def test_required_redis_requires_coordination_mode() -> None:
    with pytest.raises(ValidationError, match="REDIS_REQUIRED"):
        Settings(redis_required=True, redis_url="redis://redis:6379/0")


def test_trusted_hosts_accept_comma_separated_value() -> None:
    settings = Settings(trusted_hosts="api.example, internal.example")

    assert settings.trusted_hosts == ["api.example", "internal.example"]


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="Production DEBUG"):
        Settings(
            app_env="production",
            debug=True,
            jwt_secret_key="7c96be81bb8a4eb585409088de919e66",
            cors_origins=["https://client.example"],
            trusted_hosts=["api.example"],
        )


def test_trusted_proxy_networks_are_explicit_and_validated() -> None:
    settings = Settings(
        trusted_proxy_networks="10.0.0.7, 2001:db8::/48",
    )

    assert settings.trusted_proxy_networks == ["10.0.0.7/32", "2001:db8::/48"]
    assert Settings().trusted_proxy_networks == []
    with pytest.raises(ValidationError, match="must be IP networks"):
        Settings(trusted_proxy_networks="proxy.example")

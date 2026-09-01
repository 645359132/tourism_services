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
        Settings(app_env="production")


def test_production_rejects_demo_accounts_even_with_strong_secret() -> None:
    with pytest.raises(ValidationError, match="Demo accounts"):
        Settings(
            app_env="production",
            jwt_secret_key="7c96be81bb8a4eb585409088de919e66",
            enable_demo_accounts=True,
        )


def test_production_accepts_non_placeholder_secret() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret_key="7c96be81bb8a4eb585409088de919e66",
    )

    assert settings.app_env == "production"

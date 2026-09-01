"""Settings parsing tests."""

from app.core.config import Settings


def test_postgres_url_uses_async_driver() -> None:
    settings = Settings(database_url="postgresql://user:pass@db:5432/tourism")

    assert settings.database_url == "postgresql+asyncpg://user:pass@db:5432/tourism"


def test_cors_origins_accept_comma_separated_value() -> None:
    settings = Settings(cors_origins="https://one.example, https://two.example")

    assert settings.cors_origins == ["https://one.example", "https://two.example"]

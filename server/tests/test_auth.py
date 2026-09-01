"""Authentication, refresh-family, preferences, and RBAC integration tests."""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies.auth import require_roles
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.models.role import Role, UserRole
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.scripts.seed import DEMO_PASSWORD, seed_database
from app.services.auth import rotate_refresh_token


@dataclass(slots=True)
class AuthHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    database_path: Path
    settings: Settings


def _protected_endpoint(role_name: str) -> Callable[..., object]:
    dependency = require_roles(role_name)

    async def endpoint(
        user: Annotated[User, Depends(dependency)],
    ) -> dict[str, str]:
        return {"username": user.username, "required_role": role_name}

    return endpoint


@pytest.fixture(scope="module")
def auth_harness(tmp_path_factory: pytest.TempPathFactory) -> Iterator[AuthHarness]:
    database_path = tmp_path_factory.mktemp("auth") / "auth.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await seed_database(session_factory, include_demo_accounts=True)

        async with session_factory() as session:
            tourist_role = await session.scalar(select(Role).where(Role.name == "tourist"))
            assert tourist_role is not None
            disabled_user = User(
                username="disabled_demo",
                display_name="Disabled Demo",
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=False,
            )
            session.add(disabled_user)
            await session.flush()
            session.add(UserRole(user_id=disabled_user.id, role_id=tourist_role.id))
            await session.commit()

    asyncio.run(prepare_database())
    asyncio.run(engine.dispose())

    settings = Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="test-suite-jwt-secret-9f6c4abed56a7b31",
        enable_demo_accounts=True,
        log_level="CRITICAL",
    )
    application = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    for role_name in ("tourist", "merchant", "support", "admin"):
        application.add_api_route(
            f"/api/v1/test/roles/{role_name}",
            _protected_endpoint(role_name),
            methods=["GET"],
        )

    with TestClient(application) as client:
        yield AuthHarness(client, session_factory, database_path, settings)

    asyncio.run(engine.dispose())


def _login(client: TestClient, username: str, password: str = DEMO_PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_login_matches_client_contract(auth_harness: AuthHarness) -> None:
    response = _login(auth_harness.client, " TOURIST_DEMO ")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
        "user",
    }
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert set(body["user"]) == {"id", "username", "display_name", "roles"}
    UUID(body["user"]["id"])
    assert body["user"]["username"] == "tourist_demo"
    assert body["user"]["roles"] == ["tourist"]


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("missing_demo", DEMO_PASSWORD),
        ("tourist_demo", "incorrect-password"),
    ],
)
def test_invalid_login_does_not_reveal_account_state(
    auth_harness: AuthHarness,
    username: str,
    password: str,
) -> None:
    response = _login(auth_harness.client, username, password)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid username or password",
    }


def test_disabled_user_cannot_login(auth_harness: AuthHarness) -> None:
    response = _login(auth_harness.client, "disabled_demo")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_refresh_rotation_detects_replay_and_revokes_descendant(
    auth_harness: AuthHarness,
) -> None:
    login_body = _login(auth_harness.client, "tourist_demo").json()
    first_refresh = login_body["refresh_token"]

    rotated = auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert rotated.status_code == 200
    second_refresh = rotated.json()["refresh_token"]
    assert second_refresh != first_refresh

    replay = auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    descendant = auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": second_refresh},
    )
    assert descendant.status_code == 401


def test_concurrent_refresh_has_one_winner_then_revokes_family(
    auth_harness: AuthHarness,
) -> None:
    original = _login(auth_harness.client, "support_demo").json()["refresh_token"]

    async def race_refreshes() -> list[str]:
        async def attempt() -> str:
            async with auth_harness.session_factory() as session:
                try:
                    result = await rotate_refresh_token(
                        session,
                        refresh_token=original,
                        settings=auth_harness.settings,
                    )
                    return result.refresh_token
                except AppError as exc:
                    return exc.code

        return list(await asyncio.gather(attempt(), attempt()))

    outcomes = asyncio.run(race_refreshes())
    winners = [outcome for outcome in outcomes if outcome.count(".") == 2]
    assert len(winners) == 1
    assert "REFRESH_TOKEN_REUSED" in outcomes

    family_is_revoked = auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": winners[0]},
    )
    assert family_is_revoked.status_code == 401


def test_logout_is_idempotent_and_revokes_family(auth_harness: AuthHarness) -> None:
    refresh_token = _login(auth_harness.client, "merchant_demo").json()["refresh_token"]

    first_logout = auth_harness.client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )
    second_logout = auth_harness.client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )

    assert first_logout.status_code == 204
    assert second_logout.status_code == 204
    rejected = auth_harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert rejected.status_code == 401


def test_me_accepts_access_token_but_not_refresh_token(auth_harness: AuthHarness) -> None:
    tokens = _login(auth_harness.client, "support_demo").json()

    accepted = auth_harness.client.get(
        "/api/v1/users/me",
        headers=_bearer(tokens["access_token"]),
    )
    rejected = auth_harness.client.get(
        "/api/v1/users/me",
        headers=_bearer(tokens["refresh_token"]),
    )

    assert accepted.status_code == 200
    assert accepted.json()["roles"] == ["support"]
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


@pytest.mark.parametrize("role_name", ["tourist", "merchant", "support", "admin"])
def test_role_dependencies_allow_exact_role_and_admin(
    auth_harness: AuthHarness,
    role_name: str,
) -> None:
    exact_token = _login(auth_harness.client, f"{role_name}_demo").json()["access_token"]
    exact = auth_harness.client.get(
        f"/api/v1/test/roles/{role_name}",
        headers=_bearer(exact_token),
    )
    assert exact.status_code == 200, exact.json()

    if role_name != "admin":
        admin_token = _login(auth_harness.client, "admin_demo").json()["access_token"]
        admin = auth_harness.client.get(
            f"/api/v1/test/roles/{role_name}",
            headers=_bearer(admin_token),
        )
        assert admin.status_code == 200


def test_role_dependency_rejects_other_role(auth_harness: AuthHarness) -> None:
    merchant_token = _login(auth_harness.client, "merchant_demo").json()["access_token"]

    response = auth_harness.client.get(
        "/api/v1/test/roles/tourist",
        headers=_bearer(merchant_token),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_tourist_can_patch_only_own_preferences(auth_harness: AuthHarness) -> None:
    tourist_token = _login(auth_harness.client, "tourist_demo").json()["access_token"]
    response = auth_harness.client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(tourist_token),
        json={
            "preferred_language": "en-US",
            "interests": ["museums", " museums ", "hiking"],
            "notifications_enabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["preferred_language"] == "en-US"
    assert response.json()["interests"] == ["museums", "hiking"]
    assert response.json()["notifications_enabled"] is False

    merchant_token = _login(auth_harness.client, "merchant_demo").json()["access_token"]
    forbidden = auth_harness.client.patch(
        "/api/v1/users/me/preferences",
        headers=_bearer(merchant_token),
        json={"interests": ["not-owned"]},
    )
    assert forbidden.status_code == 403


def test_capabilities_are_public_stable_metadata(auth_harness: AuthHarness) -> None:
    response = auth_harness.client.get("/api/v1/meta/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == {
        "admin": ["*"],
        "merchant": ["merchant:manage", "profile:read"],
        "support": ["profile:read", "support:assist"],
        "tourist": ["preferences:read", "preferences:write", "profile:read"],
    }
    assert {name: provider["mode"] for name, provider in body["providers"].items()} == {
        "ai": "rules",
        "crowd": "simulated",
        "gate": "demo",
        "map": "schematic",
        "merchant": "demo",
        "notification": "in_process",
        "payment": "demo",
    }
    assert all(provider["is_demo"] is True for provider in body["providers"].values())


def test_seed_database_contains_hashes_not_plaintext(auth_harness: AuthHarness) -> None:
    async def read_hashes() -> list[str]:
        async with auth_harness.session_factory() as session:
            return list(
                await session.scalars(
                    select(User.password_hash).where(User.username.like("%_demo"))
                )
            )

    hashes = asyncio.run(read_hashes())
    assert hashes
    assert all(encoded_hash != DEMO_PASSWORD for encoded_hash in hashes)
    assert all(encoded_hash.startswith("$argon2id$") for encoded_hash in hashes)
    assert all(verify_password(DEMO_PASSWORD, encoded_hash) for encoded_hash in hashes)
    assert DEMO_PASSWORD.encode() not in auth_harness.database_path.read_bytes()

"""Focused tests for the real-network smoke and load-support helpers."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401  # Register every relationship before create_all.
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.db.models.preference import TouristPreference
from app.db.models.role import Role, UserRole
from app.db.models.user import User
from app.scripts import load_seed as load_seed_module
from app.scripts.load_seed import (
    MAX_LOAD_USER_COUNT,
    LoadSeedResult,
    load_username,
    seed_load_users,
)
from app.scripts.smoke import SmokeFailure, require_items, require_object
from app.scripts.smoke import websocket_url as smoke_websocket_url
from load.common import (
    ScenarioDataMissing,
    UniqueUserAllocator,
    UserPoolExhausted,
    env_int,
    require_scenario_item,
    websocket_url,
)


class RecordingRequestEvent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fire(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def test_unique_user_allocator_never_shares_an_identity() -> None:
    allocator = UniqueUserAllocator(prefix="load_", count=2, offset=10)

    assert allocator.claim().username == "load_00011"
    assert allocator.claim().username == "load_00012"
    with pytest.raises(UserPoolExhausted, match="all 2 load identities"):
        allocator.claim()

    allocator.reset()
    assert allocator.claim().index == 11
    with pytest.raises(ValueError, match="exceeds"):
        UniqueUserAllocator(prefix="load_", count=2, offset=9_999)


@pytest.mark.parametrize(
    ("scenario", "items", "predicate"),
    [
        ("ticket catalogue available", [], None),
        (
            "ticket inventory available",
            [{"remaining": 0}],
            lambda item: int(item.get("remaining", 0)) > 0,
        ),
        ("reservation catalogue available", [], None),
        (
            "reservation session inventory available",
            [{"remaining": 0}],
            lambda item: int(item.get("remaining", 0)) > 0,
        ),
        (
            "shop inventory available",
            [{"stock": 0}],
            lambda item: int(item.get("stock", 0)) > 0,
        ),
    ],
)
def test_missing_required_scenario_data_emits_failure(
    scenario: str,
    items: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool] | None,
) -> None:
    event = RecordingRequestEvent()

    with pytest.raises(ScenarioDataMissing, match="required data missing") as caught:
        require_scenario_item(
            event,
            items,
            scenario=scenario,
            reason=f"{scenario}: required data missing",
            predicate=predicate,
        )

    assert len(event.calls) == 1
    assert event.calls[0] == {
        "request_type": "SCENARIO",
        "name": scenario,
        "response_time": 0,
        "response_length": 0,
        "exception": caught.value,
    }


def test_bounded_environment_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_TEST_INTEGER", "7")
    assert env_int("LOAD_TEST_INTEGER", 1, minimum=1, maximum=10) == 7

    monkeypatch.setenv("LOAD_TEST_INTEGER", "many")
    with pytest.raises(ValueError, match="must be an integer"):
        env_int("LOAD_TEST_INTEGER", 1)

    monkeypatch.setenv("LOAD_TEST_INTEGER", "11")
    with pytest.raises(ValueError, match="between 1 and 10"):
        env_int("LOAD_TEST_INTEGER", 1, minimum=1, maximum=10)


def test_websocket_urls_preserve_prefix_and_encode_tickets() -> None:
    expected = "wss://example.test/root/api/v1/ws/queues/1?ticket=a%2Fb%3D"
    query = {"ticket": "a/b="}

    assert websocket_url("https://example.test/root/", "/api/v1/ws/queues/1", query) == expected
    assert (
        smoke_websocket_url(
            "https://example.test/root/",
            "/api/v1/ws/queues/1",
            query,
        )
        == expected
    )
    with pytest.raises(ValueError, match="absolute"):
        websocket_url("localhost:8000", "/ws")


def test_smoke_json_contract_helpers_fail_loudly() -> None:
    assert require_object({"status": "ok"}, label="health") == {"status": "ok"}
    assert require_items({"items": [{"id": "1"}]}, label="catalog") == [{"id": "1"}]

    with pytest.raises(SmokeFailure, match="JSON object"):
        require_object([], label="health")
    with pytest.raises(SmokeFailure, match="non-empty"):
        require_items({"items": []}, label="catalog")


def test_load_username_validation() -> None:
    assert load_username(1) == "load_tourist_00001"
    assert load_username(MAX_LOAD_USER_COUNT).endswith("10000")
    with pytest.raises(ValueError, match="index"):
        load_username(0)
    with pytest.raises(ValueError, match="prefix"):
        load_username(1, prefix="unsafe-prefix-")


async def test_load_seed_is_idempotent_and_rotates_the_shared_password() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        session.add(Role(name="tourist", description="load-test tourist"))
        await session.commit()

    first = await seed_load_users(
        count=3,
        prefix="perf_user_",
        password="InitialLoadPassword!",
        session_factory=factory,
    )
    assert (first.created, first.repaired, first.unchanged) == (3, 0, 0)

    async with factory() as session:
        users = list(await session.scalars(select(User).order_by(User.username)))
        assert [user.username for user in users] == [
            "perf_user_00001",
            "perf_user_00002",
            "perf_user_00003",
        ]
        assert all(verify_password("InitialLoadPassword!", user.password_hash) for user in users)
        role_id = await session.scalar(select(Role.id).where(Role.name == "tourist"))
        assert role_id is not None
        users[0].is_active = False
        users[0].password_hash = hash_password("StaleLoadPassword!")
        role_link = await session.get(
            UserRole,
            {"user_id": users[0].id, "role_id": role_id},
        )
        preference = await session.get(TouristPreference, users[0].id)
        assert role_link is not None
        assert preference is not None
        await session.delete(role_link)
        await session.delete(preference)
        await session.commit()

    rotated = await seed_load_users(
        count=3,
        prefix="perf_user_",
        password="RotatedLoadPassword!",
        session_factory=factory,
    )
    assert (rotated.created, rotated.repaired, rotated.unchanged) == (0, 3, 0)

    unchanged = await seed_load_users(
        count=3,
        prefix="perf_user_",
        password="RotatedLoadPassword!",
        session_factory=factory,
    )
    assert (unchanged.created, unchanged.repaired, unchanged.unchanged) == (0, 0, 3)

    async with factory() as session:
        users = list(await session.scalars(select(User).order_by(User.username)))
        assert all(user.is_active for user in users)
        assert all(verify_password("RotatedLoadPassword!", user.password_hash) for user in users)
        first_user_id = UUID(str(users[0].id))
        assert await session.get(TouristPreference, first_user_id) is not None
        role_count = await session.scalar(
            select(func.count()).select_from(UserRole).where(UserRole.user_id == first_user_id)
        )
        assert role_count == 1

    await engine.dispose()


async def test_load_seed_main_disposes_database_on_the_same_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loop = asyncio.get_running_loop()
    calls: list[tuple[str, asyncio.AbstractEventLoop]] = []

    async def fake_foundation_seed(*, include_demo_accounts: bool) -> bool:
        assert include_demo_accounts is True
        calls.append(("foundation", asyncio.get_running_loop()))
        return True

    async def fake_load_seed(**kwargs: object) -> LoadSeedResult:
        assert kwargs == {
            "count": 2,
            "prefix": "loop_user_",
            "password": "LoopBoundPassword!",
        }
        calls.append(("load", asyncio.get_running_loop()))
        return LoadSeedResult(requested=2, created=2, repaired=0)

    async def fake_dispose() -> None:
        calls.append(("dispose", asyncio.get_running_loop()))

    monkeypatch.setattr(
        load_seed_module,
        "get_settings",
        lambda: SimpleNamespace(app_env="test"),
    )
    monkeypatch.setattr(load_seed_module, "seed_database", fake_foundation_seed)
    monkeypatch.setattr(load_seed_module, "seed_load_users", fake_load_seed)
    monkeypatch.setattr(load_seed_module, "dispose_database", fake_dispose)

    await load_seed_module._main(
        argparse.Namespace(
            count=2,
            prefix="loop_user_",
            password="LoopBoundPassword!",
        )
    )

    assert calls == [("foundation", loop), ("load", loop), ("dispose", loop)]
    output = capsys.readouterr().out
    assert "LoopBoundPassword!" not in output
    assert "created=2" in output


async def test_load_seed_main_disposes_database_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def failed_foundation_seed(*, include_demo_accounts: bool) -> bool:
        assert include_demo_accounts is True
        calls.append("foundation")
        raise RuntimeError("seed failed")

    async def fake_dispose() -> None:
        calls.append("dispose")

    monkeypatch.setattr(
        load_seed_module,
        "get_settings",
        lambda: SimpleNamespace(app_env="test"),
    )
    monkeypatch.setattr(load_seed_module, "seed_database", failed_foundation_seed)
    monkeypatch.setattr(load_seed_module, "dispose_database", fake_dispose)

    with pytest.raises(RuntimeError, match="seed failed"):
        await load_seed_module._main(
            argparse.Namespace(
                count=1,
                prefix="loop_user_",
                password="LoopBoundPassword!",
            )
        )

    assert calls == ["foundation", "dispose"]


def test_load_seed_cli_uses_one_asyncio_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(
        count=1,
        prefix="loop_user_",
        password="LoopBoundPassword!",
    )

    class FakeParser:
        @staticmethod
        def parse_args() -> argparse.Namespace:
            return args

    received: list[argparse.Namespace] = []

    async def fake_main(parsed: argparse.Namespace) -> None:
        received.append(parsed)

    real_asyncio_run = asyncio.run
    run_calls = 0

    def counting_run(coroutine: Any) -> object:
        nonlocal run_calls
        run_calls += 1
        return real_asyncio_run(coroutine)

    monkeypatch.setattr(load_seed_module, "_parser", FakeParser)
    monkeypatch.setattr(load_seed_module, "_main", fake_main)
    monkeypatch.setattr(load_seed_module.asyncio, "run", counting_run)

    load_seed_module.run()

    assert run_calls == 1
    assert received == [args]

"""Checkpoint 6 marketplace, inventory, queue, and realtime integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.marketplace import (
    BundleComponent,
    Experience,
    ExperienceSession,
    FastPass,
    HospitalityOffer,
    InventoryBucket,
    Reservation,
    UserScheduleLock,
)
from app.db.models.role import Role, UserRole
from app.db.models.ticketing import TicketOrder, TicketSlot
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.scripts.seed import DEMO_PASSWORD, seed_database
from app.services.auth import get_user_by_id
from app.services.queues import buy_fast_pass, join_queue
from app.services.reservations import create_experience_reservation
from app.services.ticketing import create_ticket_order


@dataclass(slots=True)
class MarketplaceHarness:
    client: TestClient
    application: FastAPI
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings


@pytest.fixture(scope="module")
def marketplace_harness(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[MarketplaceHarness]:
    database_path: Path = tmp_path_factory.mktemp("marketplace") / "marketplace.db"
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
            for username in (
                "market_tourist_two",
                "market_tourist_three",
                "market_race_one",
                "market_race_two",
                "market_cross",
                "market_res_first",
            ):
                user = User(
                    username=username,
                    display_name=username,
                    password_hash=hash_password(DEMO_PASSWORD),
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                session.add(UserRole(user_id=user.id, role_id=tourist_role.id))
                session.add(UserScheduleLock(user_id=user.id, version=1))
            await session.commit()

    asyncio.run(prepare_database())
    asyncio.run(engine.dispose())
    settings = Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="marketplace-test-jwt-secret-f53c51ef959b",
        enable_demo_accounts=True,
        crowd_publish_interval_seconds=3600,
        queue_publish_interval_seconds=3600,
        reservation_walking_buffer_minutes=10,
        log_level="CRITICAL",
    )
    application = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    application.state.crowd_publisher.session_factory_provider = lambda: session_factory
    application.state.queue_publisher.session_factory_provider = lambda: session_factory
    with TestClient(application) as client:
        yield MarketplaceHarness(client, application, session_factory, settings)
    asyncio.run(engine.dispose())


def _login(harness: MarketplaceHarness, username: str) -> str:
    response = harness.client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.json()
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _visit_date(day_offset: int = 1) -> str:
    return (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=day_offset)).isoformat()


def test_experience_reservation_contract_and_atomic_lifecycle(
    marketplace_harness: MarketplaceHarness,
) -> None:
    catalog = marketplace_harness.client.get("/api/v1/experiences")
    assert catalog.status_code == 200
    experience = catalog.json()["items"][0]
    assert set(experience) == {
        "id",
        "code",
        "kind",
        "name",
        "description",
        "node_id",
        "duration_minutes",
        "min_height_cm",
        "fastpass_allowed",
        "fastpass_price_cents",
        "accessibility",
        "wait_minutes",
    }
    sessions = marketplace_harness.client.get(
        f"/api/v1/experiences/{experience['id']}/sessions",
        params={"date": _visit_date()},
    )
    assert sessions.status_code == 200
    experience_session = sessions.json()["items"][0]
    assert set(experience_session) == {
        "id",
        "experience_id",
        "experience_name",
        "starts_at",
        "ends_at",
        "capacity",
        "remaining",
        "status",
    }

    token = _login(marketplace_harness, "tourist_demo")
    payload = {
        "session_id": experience_session["id"],
        "party_size": 2,
        "idempotency_key": "experience-create-0001",
    }
    created = marketplace_harness.client.post(
        "/api/v1/reservations",
        headers=_bearer(token),
        json=payload,
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert set(body) == {
        "id",
        "booking_no",
        "kind",
        "resource_type",
        "resource_id",
        "resource_name",
        "starts_at",
        "ends_at",
        "party_size",
        "quantity",
        "total_cents",
        "status",
        "provider",
        "is_demo",
        "allocations",
    }
    assert body["status"] == "HELD"
    assert body["quantity"] == 2
    assert len(body["allocations"]) == 1

    replay = marketplace_harness.client.post(
        "/api/v1/reservations",
        headers=_bearer(token),
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == body["id"]
    conflict = marketplace_harness.client.post(
        "/api/v1/reservations",
        headers=_bearer(token),
        json={**payload, "party_size": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    confirmed = marketplace_harness.client.post(
        f"/api/v1/reservations/{body['id']}/confirm",
        headers=_bearer(token),
        json={"idempotency_key": "experience-confirm-0001"},
    )
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["status"] == "CONFIRMED"
    cancelled = marketplace_harness.client.post(
        f"/api/v1/reservations/{body['id']}/cancel",
        headers=_bearer(token),
        json={
            "reason": "行程调整",
            "idempotency_key": "experience-cancel-0001",
        },
    )
    assert cancelled.status_code == 200, cancelled.json()
    assert cancelled.json()["status"] == "CANCELLED"

    async def read_ledger() -> tuple[str | None, int, int]:
        async with marketplace_harness.session_factory() as session:
            reservation = await session.get(Reservation, UUID(body["id"]))
            bucket = await session.get(
                InventoryBucket,
                UUID(body["allocations"][0]["bucket_id"]),
            )
            assert reservation is not None
            assert bucket is not None
            return reservation.cancel_reason, bucket.held, bucket.confirmed

    assert asyncio.run(read_ledger()) == ("行程调整", 0, 0)


def test_experience_catalog_is_not_cached_across_live_wait_changes(
    marketplace_harness: MarketplaceHarness,
) -> None:
    before = marketplace_harness.client.get("/api/v1/experiences").json()["items"][0]

    async def change_wait(wait_minutes: int) -> None:
        async with marketplace_harness.session_factory() as session:
            await session.execute(
                update(Experience)
                .where(Experience.id == UUID(before["id"]))
                .values(wait_minutes=wait_minutes)
            )
            await session.commit()

    changed_wait = before["wait_minutes"] + 13
    asyncio.run(change_wait(changed_wait))
    try:
        after = marketplace_harness.client.get("/api/v1/experiences").json()["items"][0]
        assert after["wait_minutes"] == changed_wait
    finally:
        asyncio.run(change_wait(before["wait_minutes"]))


def test_multi_night_half_open_stay_and_bundle_rollback(
    marketplace_harness: MarketplaceHarness,
) -> None:
    offers_response = marketplace_harness.client.get("/api/v1/hospitality/offers")
    assert offers_response.status_code == 200
    offers = offers_response.json()["items"]
    room = next(item for item in offers if item["code"] == "lake_room")
    bundle = next(item for item in offers if item["code"] == "stay_play_bundle")
    assert isinstance(room["attributes"], list)
    assert set(room) == {
        "id",
        "venue_id",
        "code",
        "kind",
        "name",
        "description",
        "base_price_cents",
        "capacity",
        "max_party_size",
        "provider",
        "is_demo",
        "bundle_components",
        "attributes",
    }
    availability = marketplace_harness.client.get(
        "/api/v1/hospitality/availability",
        params={
            "resource_id": room["id"],
            "date_from": _visit_date(),
            "date_to": _visit_date(4),
        },
    )
    assert availability.status_code == 200
    assert set(availability.json()["items"][0]) == {
        "bucket_id",
        "resource_type",
        "resource_id",
        "business_date",
        "start_at",
        "end_at",
        "remaining",
        "unit_price_cents",
    }

    token = _login(marketplace_harness, "market_tourist_two")
    stay = marketplace_harness.client.post(
        "/api/v1/hospitality/bookings/stay",
        headers=_bearer(token),
        json={
            "offer_id": room["id"],
            "check_in": _visit_date(),
            "check_out": _visit_date(3),
            "quantity": 1,
            "party_size": 2,
            "idempotency_key": "stay-two-nights-0001",
        },
    )
    assert stay.status_code == 201, stay.json()
    assert [item["business_date"] for item in stay.json()["allocations"]] == [
        _visit_date(),
        _visit_date(2),
    ]
    confirmed = marketplace_harness.client.post(
        f"/api/v1/reservations/{stay.json()['id']}/confirm",
        headers=_bearer(token),
        json={"idempotency_key": "stay-confirm-0001"},
    )
    assert confirmed.status_code == 200

    experience = marketplace_harness.client.get("/api/v1/experiences").json()["items"][0]
    daytime = marketplace_harness.client.get(
        f"/api/v1/experiences/{experience['id']}/sessions",
        params={"date": _visit_date(2)},
    ).json()["items"][0]
    during_stay = marketplace_harness.client.post(
        "/api/v1/reservations",
        headers=_bearer(token),
        json={
            "session_id": daytime["id"],
            "party_size": 1,
            "idempotency_key": "during-stay-activity-0001",
        },
    )
    assert during_stay.status_code == 201, during_stay.json()

    async def exhaust_later_bundle_component() -> list[UUID]:
        async with marketplace_harness.session_factory() as session:
            bundle_model = await session.scalar(
                select(HospitalityOffer).where(HospitalityOffer.id == UUID(bundle["id"]))
            )
            assert bundle_model is not None
            components = list(
                await session.scalars(
                    select(BundleComponent).where(
                        BundleComponent.bundle_offer_id == bundle_model.id
                    )
                )
            )
            bucket_ids: list[UUID] = []
            for component in components:
                if component.component_type == "ROOM":
                    bucket = await session.scalar(
                        select(InventoryBucket).where(
                            InventoryBucket.resource_type == "ROOM",
                            InventoryBucket.resource_id == component.component_resource_id,
                            InventoryBucket.business_date
                            == datetime.fromisoformat(_visit_date(4)).date(),
                        )
                    )
                else:
                    bucket = await session.scalar(
                        select(InventoryBucket)
                        .join(
                            ExperienceSession,
                            InventoryBucket.resource_id == ExperienceSession.id,
                        )
                        .where(
                            InventoryBucket.resource_type == "EXPERIENCE_SESSION",
                            ExperienceSession.experience_id == component.component_resource_id,
                            InventoryBucket.business_date
                            == datetime.fromisoformat(_visit_date(4)).date(),
                        )
                        .order_by(InventoryBucket.starts_at)
                    )
                assert bucket is not None
                bucket_ids.append(bucket.id)
            target = max(bucket_ids, key=str)
            await session.execute(
                update(InventoryBucket)
                .where(InventoryBucket.id == target)
                .values(capacity=0, held=0, confirmed=0)
            )
            await session.commit()
            return bucket_ids

    bundle_bucket_ids = asyncio.run(exhaust_later_bundle_component())
    clean_token = _login(marketplace_harness, "market_tourist_three")
    failed_bundle = marketplace_harness.client.post(
        "/api/v1/hospitality/bookings/bundle",
        headers=_bearer(clean_token),
        json={
            "offer_id": bundle["id"],
            "visit_date": _visit_date(4),
            "party_size": 2,
            "idempotency_key": "bundle-rollback-0001",
        },
    )
    assert failed_bundle.status_code == 409
    assert failed_bundle.json()["error"]["code"] == "INSUFFICIENT_INVENTORY"

    async def held_counts() -> list[int]:
        async with marketplace_harness.session_factory() as session:
            buckets = list(
                await session.scalars(
                    select(InventoryBucket).where(InventoryBucket.id.in_(bundle_bucket_ids))
                )
            )
            return [bucket.held for bucket in buckets]

    assert asyncio.run(held_counts()) == [0, 0]


def test_queue_fastpass_single_use_ws_and_terminal_close(
    marketplace_harness: MarketplaceHarness,
) -> None:
    experiences = marketplace_harness.client.get("/api/v1/experiences").json()["items"]
    fast_experiences = [item for item in experiences if item["fastpass_allowed"]]
    assert len(fast_experiences) >= 2
    owner_token = _login(marketplace_harness, "tourist_demo")
    other_token = _login(marketplace_harness, "market_tourist_three")

    first_join_payload = {
        "experience_id": fast_experiences[0]["id"],
        "party_size": 2,
        "itinerary_id": None,
        "idempotency_key": "queue-owner-first-0001",
    }
    first_queue = marketplace_harness.client.post(
        "/api/v1/queues",
        headers=_bearer(owner_token),
        json=first_join_payload,
    )
    assert first_queue.status_code == 201, first_queue.json()
    first = first_queue.json()
    assert set(first) == {
        "id",
        "queue_no",
        "experience_id",
        "experience_name",
        "status",
        "party_size",
        "estimated_wait_minutes",
        "sequence",
        "joined_at",
        "called_at",
        "itinerary_id",
        "itinerary_revision",
        "nearby_recommendations",
        "fast_pass",
    }
    replay = marketplace_harness.client.post(
        "/api/v1/queues",
        headers=_bearer(owner_token),
        json=first_join_payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first["id"]
    key_conflict = marketplace_harness.client.post(
        "/api/v1/queues",
        headers=_bearer(owner_token),
        json={**first_join_payload, "party_size": 1},
    )
    assert key_conflict.status_code == 409
    assert key_conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    second_queue = marketplace_harness.client.post(
        "/api/v1/queues",
        headers=_bearer(owner_token),
        json={
            "experience_id": fast_experiences[1]["id"],
            "party_size": 1,
            "itinerary_id": None,
            "idempotency_key": "queue-owner-second-0001",
        },
    )
    assert second_queue.status_code == 201, second_queue.json()
    second = second_queue.json()
    assert first["queue_no"] != second["queue_no"]

    other_queue = marketplace_harness.client.post(
        "/api/v1/queues",
        headers=_bearer(other_token),
        json={
            "experience_id": fast_experiences[0]["id"],
            "party_size": 1,
            "itinerary_id": None,
            "idempotency_key": "queue-other-first-0001",
        },
    )
    assert other_queue.status_code == 201, other_queue.json()
    other = other_queue.json()

    async def limit_fastpass_quota() -> UUID:
        scenic_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        async with marketplace_harness.session_factory() as session:
            bucket = await session.scalar(
                select(InventoryBucket).where(
                    InventoryBucket.resource_type == "FAST_PASS",
                    InventoryBucket.resource_id == UUID(fast_experiences[0]["id"]),
                    InventoryBucket.business_date == scenic_today,
                )
            )
            assert bucket is not None
            await session.execute(
                update(InventoryBucket)
                .where(InventoryBucket.id == bucket.id)
                .values(capacity=1, held=0, confirmed=0)
            )
            await session.commit()
            return bucket.id

    quota_bucket_id = asyncio.run(limit_fastpass_quota())
    bought = marketplace_harness.client.post(
        f"/api/v1/queues/{first['id']}/fast-pass",
        headers=_bearer(owner_token),
        json={"idempotency_key": "fastpass-owner-0001"},
    )
    assert bought.status_code == 200, bought.json()
    assert bought.json()["status"] == "ACTIVE"
    assert bought.json()["is_demo"] is True
    sold_out = marketplace_harness.client.post(
        f"/api/v1/queues/{other['id']}/fast-pass",
        headers=_bearer(other_token),
        json={"idempotency_key": "fastpass-other-0001"},
    )
    assert sold_out.status_code == 409
    assert sold_out.json()["error"]["code"] == "FAST_PASS_SOLD_OUT"

    unauthorized_ticket = marketplace_harness.client.post(
        "/api/v1/ws-tickets",
        headers=_bearer(other_token),
        json={"channel_type": "queue", "channel_id": first["id"]},
    )
    assert unauthorized_ticket.status_code == 404

    ticket = marketplace_harness.client.post(
        "/api/v1/ws-tickets",
        headers=_bearer(owner_token),
        json={"channel_type": "queue", "channel_id": first["id"]},
    )
    assert ticket.status_code == 200
    socket_path = f"/api/v1/ws/queues/{first['id']}?ticket={ticket.json()['ticket']}"
    with marketplace_harness.client.websocket_connect(socket_path) as websocket:
        initial = websocket.receive_json()
        initial_sequence = initial["data"]["queue"]["sequence"]
        portal = marketplace_harness.client.portal
        assert portal is not None
        portal.call(marketplace_harness.application.state.queue_publisher.publish_once)
        updated = websocket.receive_json()
        assert updated["data"]["queue"]["status"] == "CALLED"
        assert updated["data"]["queue"]["sequence"] > initial_sequence
        assert updated["data"]["source"] == "simulated"
    assert marketplace_harness.application.state.queue_hub.connection_count == 0

    with pytest.raises(WebSocketDisconnect) as replay_closed:
        with marketplace_harness.client.websocket_connect(socket_path) as replay_socket:
            replay_socket.receive_json()
    assert replay_closed.value.code == 4401

    bound_ticket = marketplace_harness.client.post(
        "/api/v1/ws-tickets",
        headers=_bearer(owner_token),
        json={"channel_type": "queue", "channel_id": first["id"]},
    ).json()["ticket"]
    wrong_path = f"/api/v1/ws/queues/{second['id']}?ticket={bound_ticket}"
    with pytest.raises(WebSocketDisconnect) as wrong_closed:
        with marketplace_harness.client.websocket_connect(wrong_path) as wrong_socket:
            wrong_socket.receive_json()
    assert wrong_closed.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as burned_closed:
        with marketplace_harness.client.websocket_connect(
            f"/api/v1/ws/queues/{first['id']}?ticket={bound_ticket}"
        ) as burned_socket:
            burned_socket.receive_json()
    assert burned_closed.value.code == 4401

    left = marketplace_harness.client.request(
        "DELETE",
        f"/api/v1/queues/{first['id']}",
        headers=_bearer(owner_token),
        json={"idempotency_key": "queue-leave-owner-0001"},
    )
    assert left.status_code == 200, left.json()
    assert left.json()["status"] == "LEFT"
    assert left.json()["fast_pass"]["status"] == "CANCELLED"
    leave_replay = marketplace_harness.client.request(
        "DELETE",
        f"/api/v1/queues/{first['id']}",
        headers=_bearer(owner_token),
        json={"idempotency_key": "queue-leave-owner-0001"},
    )
    assert leave_replay.status_code == 200
    terminal_ticket = marketplace_harness.client.post(
        "/api/v1/ws-tickets",
        headers=_bearer(owner_token),
        json={"channel_type": "queue", "channel_id": first["id"]},
    )
    assert terminal_ticket.status_code == 409

    async def quota_after_leave() -> int:
        async with marketplace_harness.session_factory() as session:
            bucket = await session.get(InventoryBucket, quota_bucket_id)
            assert bucket is not None
            return bucket.confirmed

    assert asyncio.run(quota_after_leave()) == 0

    other_ticket = marketplace_harness.client.post(
        "/api/v1/ws-tickets",
        headers=_bearer(other_token),
        json={"channel_type": "queue", "channel_id": other["id"]},
    ).json()["ticket"]
    with marketplace_harness.client.websocket_connect(
        f"/api/v1/ws/queues/{other['id']}?ticket={other_ticket}"
    ) as terminal_socket:
        terminal_socket.receive_json()
        portal = marketplace_harness.client.portal
        assert portal is not None
        statuses: list[str] = []
        for _ in range(3):
            portal.call(marketplace_harness.application.state.queue_publisher.publish_once)
            statuses.append(terminal_socket.receive_json()["data"]["queue"]["status"])
        assert statuses == ["CALLED", "SERVING", "COMPLETED"]
        with pytest.raises(WebSocketDisconnect) as terminal_closed:
            terminal_socket.receive_json()
        assert terminal_closed.value.code == 1000
    assert marketplace_harness.application.state.queue_hub.connection_count == 0


def test_atomic_inventory_race_and_committed_global_expiry(
    marketplace_harness: MarketplaceHarness,
) -> None:
    async def prepare_race() -> tuple[UUID, UUID]:
        race_date = datetime.fromisoformat(_visit_date(6)).date()
        async with marketplace_harness.session_factory() as session:
            row = (
                await session.execute(
                    select(ExperienceSession, InventoryBucket)
                    .join(
                        InventoryBucket,
                        InventoryBucket.resource_id == ExperienceSession.id,
                    )
                    .where(
                        InventoryBucket.resource_type == "EXPERIENCE_SESSION",
                        InventoryBucket.business_date == race_date,
                    )
                    .order_by(ExperienceSession.starts_at)
                )
            ).first()
            assert row is not None
            experience_session, bucket = row
            await session.execute(
                update(InventoryBucket)
                .where(InventoryBucket.id == bucket.id)
                .values(capacity=1, held=0, confirmed=0)
            )
            await session.commit()
            return experience_session.id, bucket.id

    session_id, bucket_id = asyncio.run(prepare_race())

    async def race() -> tuple[list[str], UUID]:
        gate = asyncio.Event()

        async def attempt(username: str, key: str) -> tuple[str, UUID | None]:
            async with marketplace_harness.session_factory() as session:
                user_id = await session.scalar(select(User.id).where(User.username == username))
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    reservation = await create_experience_reservation(
                        session,
                        user=user,
                        session_id=session_id,
                        party_size=1,
                        idempotency_key=key,
                        settings=marketplace_harness.settings,
                    )
                    return "HELD", reservation.id
                except AppError as exc:
                    return exc.code, None

        first = asyncio.create_task(attempt("market_race_one", "race-inventory-one"))
        second = asyncio.create_task(attempt("market_race_two", "race-inventory-two"))
        gate.set()
        outcomes = await asyncio.gather(first, second)
        winner_id = next(item[1] for item in outcomes if item[0] == "HELD")
        assert winner_id is not None
        return [item[0] for item in outcomes], winner_id

    outcomes, winner_id = asyncio.run(race())
    assert sorted(outcomes) == ["HELD", "INSUFFICIENT_INVENTORY"]

    async def expire_winner() -> tuple[int, int]:
        async with marketplace_harness.session_factory() as session:
            await session.execute(
                update(Reservation)
                .where(Reservation.id == winner_id)
                .values(hold_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
        experience_id = await _experience_id_for_session(
            marketplace_harness.session_factory,
            session_id,
        )
        response = marketplace_harness.client.get(
            f"/api/v1/experiences/{experience_id}/sessions",
            params={"date": _visit_date(6)},
        )
        assert response.status_code == 200
        async with marketplace_harness.session_factory() as session:
            bucket = await session.get(InventoryBucket, bucket_id)
            reservation = await session.get(Reservation, winner_id)
            assert bucket is not None
            assert reservation is not None
            return bucket.held, int(reservation.status == "EXPIRED")

    assert asyncio.run(expire_winner()) == (0, 1)


async def _experience_id_for_session(
    factory: async_sessionmaker[AsyncSession],
    session_id: UUID,
) -> UUID:
    async with factory() as session:
        experience_id = await session.scalar(
            select(ExperienceSession.experience_id).where(ExperienceSession.id == session_id)
        )
        assert experience_id is not None
        return experience_id


def test_reservation_first_ticket_rejected_and_concurrent_cross_slice_has_one_winner(
    marketplace_harness: MarketplaceHarness,
) -> None:
    async def overlapping_pair(day_offset: int) -> tuple[UUID, UUID]:
        visit_date = datetime.fromisoformat(_visit_date(day_offset)).date()
        async with marketplace_harness.session_factory() as session:
            experience_session = await session.scalar(
                select(ExperienceSession)
                .join(
                    InventoryBucket,
                    InventoryBucket.resource_id == ExperienceSession.id,
                )
                .where(
                    InventoryBucket.resource_type == "EXPERIENCE_SESSION",
                    InventoryBucket.business_date == visit_date,
                )
                .order_by(ExperienceSession.starts_at)
            )
            assert experience_session is not None
            starts_at = experience_session.starts_at
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=UTC)
            scenic_start = starts_at.astimezone(ZoneInfo("Asia/Shanghai")).time()
            ticket_slot = await session.scalar(
                select(TicketSlot)
                .where(
                    TicketSlot.visit_date == visit_date,
                    TicketSlot.start_time <= scenic_start,
                    TicketSlot.end_time > scenic_start,
                )
                .order_by(TicketSlot.start_time)
            )
            assert ticket_slot is not None
            return experience_session.id, ticket_slot.id

    reservation_session_id, reservation_slot_id = asyncio.run(overlapping_pair(5))
    token = _login(marketplace_harness, "market_res_first")
    reserved = marketplace_harness.client.post(
        "/api/v1/reservations",
        headers=_bearer(token),
        json={
            "session_id": str(reservation_session_id),
            "party_size": 1,
            "idempotency_key": "reservation-before-ticket-0001",
        },
    )
    assert reserved.status_code == 201, reserved.json()
    ticket_rejected = marketplace_harness.client.post(
        "/api/v1/ticketing/orders",
        headers=_bearer(token),
        json={
            "slot_id": str(reservation_slot_id),
            "quantity": 1,
            "idempotency_key": "ticket-after-reservation-0001",
        },
    )
    assert ticket_rejected.status_code == 409
    assert ticket_rejected.json()["error"]["code"] == "SCHEDULE_CONFLICT"

    # 模拟用户停留在确认页直至预约占位过期。过期 HELD 记录即使尚未被列表接口清理,
    # 也不应继续阻塞同一时段的门票下单; 跨资源写操作应在用户时程锁内完成清理。
    async def expire_reservation_hold() -> None:
        async with marketplace_harness.session_factory() as session:
            await session.execute(
                update(Reservation)
                .where(Reservation.id == UUID(reserved.json()["id"]))
                .values(hold_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()

    asyncio.run(expire_reservation_hold())
    ticket_after_expiry = marketplace_harness.client.post(
        "/api/v1/ticketing/orders",
        headers=_bearer(token),
        json={
            "slot_id": str(reservation_slot_id),
            "quantity": 1,
            "idempotency_key": "ticket-after-expired-reservation-0001",
        },
    )
    assert ticket_after_expiry.status_code == 201, ticket_after_expiry.json()

    async def expired_reservation_status() -> str:
        async with marketplace_harness.session_factory() as session:
            status = await session.scalar(
                select(Reservation.status).where(
                    Reservation.id == UUID(reserved.json()["id"])
                )
            )
            assert status is not None
            return status

    assert asyncio.run(expired_reservation_status()) == "EXPIRED"

    race_session_id, race_slot_id = asyncio.run(overlapping_pair(7))

    async def cross_race() -> list[str]:
        gate = asyncio.Event()

        async def reservation_attempt() -> str:
            async with marketplace_harness.session_factory() as session:
                user_id = await session.scalar(
                    select(User.id).where(User.username == "market_cross")
                )
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await create_experience_reservation(
                        session,
                        user=user,
                        session_id=race_session_id,
                        party_size=1,
                        idempotency_key="cross-race-reservation",
                        settings=marketplace_harness.settings,
                    )
                    return "RESERVATION"
                except AppError as exc:
                    return exc.code

        async def ticket_attempt() -> str:
            async with marketplace_harness.session_factory() as session:
                user_id = await session.scalar(
                    select(User.id).where(User.username == "market_cross")
                )
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await create_ticket_order(
                        session,
                        user=user,
                        slot_id=race_slot_id,
                        quantity=1,
                        idempotency_key="cross-race-ticket",
                        settings=marketplace_harness.settings,
                    )
                    return "TICKET"
                except AppError as exc:
                    return exc.code

        reservation_task = asyncio.create_task(reservation_attempt())
        ticket_task = asyncio.create_task(ticket_attempt())
        gate.set()
        return list(await asyncio.gather(reservation_task, ticket_task))

    results = asyncio.run(cross_race())
    assert "SCHEDULE_CONFLICT" in results
    assert sum(item in {"RESERVATION", "TICKET"} for item in results) == 1

    async def persisted_winner_count() -> int:
        async with marketplace_harness.session_factory() as session:
            reservation_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Reservation)
                    .where(
                        Reservation.resource_id == race_session_id,
                        Reservation.status == "HELD",
                    )
                )
                or 0
            )
            ticket_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(TicketOrder)
                    .where(TicketOrder.idempotency_key == "cross-race-ticket")
                )
                or 0
            )
            return reservation_count + ticket_count

    assert asyncio.run(persisted_winner_count()) == 1


def test_concurrent_active_queue_and_last_fastpass_quota_have_single_winners(
    marketplace_harness: MarketplaceHarness,
) -> None:
    async def ids() -> tuple[UUID, UUID]:
        async with marketplace_harness.session_factory() as session:
            non_fast_id = await session.scalar(
                select(InventoryBucket.resource_id)
                .where(InventoryBucket.resource_type == "FAST_PASS")
                .limit(1)
            )
            assert non_fast_id is not None
            fast_ids = list(
                await session.scalars(
                    select(InventoryBucket.resource_id)
                    .where(InventoryBucket.resource_type == "FAST_PASS")
                    .distinct()
                )
            )
            assert fast_ids
            experience_ids = list(
                await session.scalars(select(ExperienceSession.experience_id).distinct())
            )
            queue_only_id = next(
                experience_id
                for experience_id in experience_ids
                if experience_id not in set(fast_ids)
            )
            return queue_only_id, fast_ids[0]

    queue_only_id, fast_experience_id = asyncio.run(ids())

    async def concurrent_joins() -> list[str]:
        gate = asyncio.Event()

        async def attempt(key: str) -> str:
            async with marketplace_harness.session_factory() as session:
                user_id = await session.scalar(
                    select(User.id).where(User.username == "market_race_one")
                )
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await join_queue(
                        session,
                        user=user,
                        experience_id=queue_only_id,
                        party_size=1,
                        itinerary_id=None,
                        idempotency_key=key,
                    )
                    return "JOINED"
                except AppError as exc:
                    return exc.code

        tasks = [
            asyncio.create_task(attempt("queue-race-key-one")),
            asyncio.create_task(attempt("queue-race-key-two")),
        ]
        gate.set()
        return list(await asyncio.gather(*tasks))

    assert sorted(asyncio.run(concurrent_joins())) == ["JOINED", "QUEUE_ALREADY_ACTIVE"]

    async def prepare_fastpass_race() -> tuple[UUID, UUID, UUID]:
        scenic_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        async with marketplace_harness.session_factory() as session:
            users = {
                user.username: user
                for user in await session.scalars(
                    select(User).where(User.username.in_(("market_race_one", "market_race_two")))
                )
            }
            contexts = []
            for username, key in (
                ("market_race_one", "fast-queue-race-one"),
                ("market_race_two", "fast-queue-race-two"),
            ):
                loaded = await get_user_by_id(session, users[username].id)
                assert loaded is not None
                contexts.append(
                    await join_queue(
                        session,
                        user=loaded,
                        experience_id=fast_experience_id,
                        party_size=1,
                        itinerary_id=None,
                        idempotency_key=key,
                    )
                )
            bucket = await session.scalar(
                select(InventoryBucket).where(
                    InventoryBucket.resource_type == "FAST_PASS",
                    InventoryBucket.resource_id == fast_experience_id,
                    InventoryBucket.business_date == scenic_today,
                )
            )
            assert bucket is not None
            await session.execute(
                update(InventoryBucket)
                .where(InventoryBucket.id == bucket.id)
                .values(capacity=1, held=0, confirmed=0)
            )
            await session.commit()
            return contexts[0].entry.id, contexts[1].entry.id, bucket.id

    first_queue_id, second_queue_id, quota_id = asyncio.run(prepare_fastpass_race())

    async def concurrent_fastpasses() -> list[str]:
        gate = asyncio.Event()

        async def attempt(username: str, queue_id: UUID, key: str) -> str:
            async with marketplace_harness.session_factory() as session:
                user_id = await session.scalar(select(User.id).where(User.username == username))
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await buy_fast_pass(
                        session,
                        queue_id=queue_id,
                        user=user,
                        idempotency_key=key,
                        settings=marketplace_harness.settings,
                    )
                    return "BOUGHT"
                except AppError as exc:
                    return exc.code

        tasks = [
            asyncio.create_task(
                attempt(
                    "market_race_one",
                    first_queue_id,
                    "fastpass-race-key-one",
                )
            ),
            asyncio.create_task(
                attempt(
                    "market_race_two",
                    second_queue_id,
                    "fastpass-race-key-two",
                )
            ),
        ]
        gate.set()
        return list(await asyncio.gather(*tasks))

    assert sorted(asyncio.run(concurrent_fastpasses())) == ["BOUGHT", "FAST_PASS_SOLD_OUT"]

    async def quota_ledger() -> tuple[int, int]:
        async with marketplace_harness.session_factory() as session:
            bucket = await session.get(InventoryBucket, quota_id)
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(FastPass)
                    .where(FastPass.queue_entry_id.in_((first_queue_id, second_queue_id)))
                )
                or 0
            )
            assert bucket is not None
            return bucket.confirmed, count

    assert asyncio.run(quota_ledger()) == (1, 1)


def test_reviews_require_completed_visit_and_duplicate_is_structured(
    marketplace_harness: MarketplaceHarness,
) -> None:
    token = _login(marketplace_harness, "market_tourist_two")

    async def confirmed_stay_id() -> UUID:
        async with marketplace_harness.session_factory() as session:
            user_id = await session.scalar(
                select(User.id).where(User.username == "market_tourist_two")
            )
            assert user_id is not None
            reservation_id = await session.scalar(
                select(Reservation.id).where(
                    Reservation.user_id == user_id,
                    Reservation.kind == "STAY",
                    Reservation.status == "CONFIRMED",
                )
            )
            assert reservation_id is not None
            return reservation_id

    reservation_id = asyncio.run(confirmed_stay_id())
    future_review = marketplace_harness.client.post(
        "/api/v1/reviews",
        headers=_bearer(token),
        json={
            "reservation_id": str(reservation_id),
            "rating": 5,
            "content": "尚未完成不应发布",
        },
    )
    assert future_review.status_code == 409
    assert future_review.json()["error"]["code"] == "REVIEW_NOT_ALLOWED"

    async def complete_time_window() -> None:
        now = datetime.now(UTC)
        async with marketplace_harness.session_factory() as session:
            await session.execute(
                update(Reservation)
                .where(Reservation.id == reservation_id)
                .values(
                    starts_at=now - timedelta(hours=2),
                    ends_at=now - timedelta(hours=1),
                )
            )
            await session.commit()

    asyncio.run(complete_time_window())
    review = marketplace_harness.client.post(
        "/api/v1/reviews",
        headers=_bearer(token),
        json={
            "reservation_id": str(reservation_id),
            "rating": 5,
            "content": "完成后的真实演示评价",
        },
    )
    assert review.status_code == 201, review.json()
    assert review.json()["status"] == "PUBLISHED"
    duplicate = marketplace_harness.client.post(
        "/api/v1/reviews",
        headers=_bearer(token),
        json={
            "reservation_id": str(reservation_id),
            "rating": 4,
            "content": "重复评价",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "REVIEW_ALREADY_EXISTS"

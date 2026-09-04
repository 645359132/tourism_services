"""Guide graph, rules itinerary, conflicts, replanning, ownership, and WS tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.guide import Attraction, CrowdSnapshot, Itinerary, ItineraryItem
from app.db.models.role import Role, UserRole
from app.db.models.ticketing import TicketSlot, TicketType
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.scripts.seed import DEMO_PASSWORD, seed_database


@dataclass(slots=True)
class GuideHarness:
    client: TestClient
    application: FastAPI
    session_factory: async_sessionmaker[AsyncSession]
    database_path: Path


@pytest.fixture(scope="module")
def guide_harness(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GuideHarness]:
    database_path = tmp_path_factory.mktemp("guide") / "guide.db"
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
            second = User(
                username="guide_tourist_two",
                display_name="Guide Tourist Two",
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            session.add(second)
            await session.flush()
            session.add(UserRole(user_id=second.id, role_id=tourist_role.id))
            await session.commit()

    asyncio.run(prepare_database())
    asyncio.run(engine.dispose())
    settings = Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="guide-test-jwt-secret-f8cf403c5ed546a9",
        enable_demo_accounts=True,
        crowd_publish_interval_seconds=3600,
        log_level="CRITICAL",
    )
    application = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    application.state.crowd_publisher.session_factory_provider = lambda: session_factory
    with TestClient(application) as client:
        yield GuideHarness(client, application, session_factory, database_path)
    asyncio.run(engine.dispose())


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _ticket_slot(
    factory: async_sessionmaker[AsyncSession],
    *,
    date_index: int,
) -> TicketSlot:
    async with factory() as session:
        adult = await session.scalar(select(TicketType).where(TicketType.code == "adult"))
        assert adult is not None
        slots = list(
            await session.scalars(
                select(TicketSlot)
                .where(TicketSlot.ticket_type_id == adult.id)
                .order_by(TicketSlot.visit_date, TicketSlot.start_time)
            )
        )
        distinct_dates = sorted({slot.visit_date for slot in slots})
        visit_date = distinct_dates[date_index]
        return next(slot for slot in slots if slot.visit_date == visit_date)


def _purchase_ticket(
    harness: GuideHarness,
    *,
    token: str,
    date_index: int,
    key_prefix: str,
) -> TicketSlot:
    slot = asyncio.run(_ticket_slot(harness.session_factory, date_index=date_index))
    created = harness.client.post(
        "/api/v1/ticketing/orders",
        headers=_bearer(token),
        json={
            "slot_id": str(slot.id),
            "quantity": 1,
            "idempotency_key": f"{key_prefix}-create",
        },
    )
    assert created.status_code == 201
    paid = harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/pay",
        headers=_bearer(token),
        json={"idempotency_key": f"{key_prefix}-payment"},
    )
    assert paid.status_code == 200
    return slot


def _generate_payload(visit_date: str) -> dict[str, object]:
    return {
        "visit_date": visit_date,
        "start_time": "08:00:00",
        "duration_minutes": 720,
        "interests": ["history", "nature", "photo"],
        "companion_type": "solo",
        "fitness_level": "medium",
        "accessible": False,
    }


def test_guide_contracts_and_simulation_boundaries(guide_harness: GuideHarness) -> None:
    attractions = guide_harness.client.get("/api/v1/guide/attractions")
    guide_map = guide_harness.client.get("/api/v1/guide/map")
    crowd = guide_harness.client.get("/api/v1/guide/crowd")

    assert attractions.status_code == 200
    assert len(attractions.json()["items"]) == 8
    assert all(item["node_id"] for item in attractions.json()["items"])
    first = attractions.json()["items"][0]
    narration = guide_harness.client.get(f"/api/v1/guide/attractions/{first['id']}/narrations")
    assert narration.status_code == 200
    assert narration.json()["items"][0]["provider_mode"] == "text_demo"
    assert narration.json()["items"][0]["audio_url"] == ""

    assert guide_map.json()["provider"]["mode"] == "schematic"
    assert guide_map.json()["provider"]["is_demo"] is True
    assert {node["kind"] for node in guide_map.json()["nodes"]} >= {
        "ENTRANCE",
        "TOILET",
        "MEDICAL",
        "REST",
    }
    assert crowd.json()["source"] == "simulated"
    assert crowd.json()["is_demo"] is True
    assert crowd.json()["sequence"] == 1
    assert all(item["source"] == "simulated" for item in crowd.json()["items"])
    assert {item["level"] for item in crowd.json()["items"]} == {
        "LOW",
        "MEDIUM",
        "HIGH",
    }


def test_attraction_catalog_is_not_cached_across_live_crowd_changes(
    guide_harness: GuideHarness,
) -> None:
    before = guide_harness.client.get("/api/v1/guide/attractions").json()["items"][0]

    async def change_wait(wait_minutes: int) -> None:
        async with guide_harness.session_factory() as session:
            await session.execute(
                update(CrowdSnapshot)
                .where(CrowdSnapshot.attraction_id == UUID(before["id"]))
                .values(wait_minutes=wait_minutes)
            )
            await session.commit()

    changed_wait = before["wait_minutes"] + 17
    asyncio.run(change_wait(changed_wait))
    try:
        after = guide_harness.client.get("/api/v1/guide/attractions").json()["items"][0]
        assert after["wait_minutes"] == changed_wait
    finally:
        asyncio.run(change_wait(before["wait_minutes"]))


def test_schematic_route_hard_filters_wheelchair_edges(guide_harness: GuideHarness) -> None:
    guide_map = guide_harness.client.get("/api/v1/guide/map").json()
    nodes = {node["code"]: node for node in guide_map["nodes"]}
    direct = guide_harness.client.post(
        "/api/v1/guide/routes/plan",
        json={
            "from_node_id": nodes["node_craft"]["id"],
            "to_node_id": nodes["node_tower"]["id"],
            "wheelchair": False,
            "stroller": False,
        },
    )
    wheelchair = guide_harness.client.post(
        "/api/v1/guide/routes/plan",
        json={
            "from_node_id": nodes["node_craft"]["id"],
            "to_node_id": nodes["node_tower"]["id"],
            "wheelchair": True,
            "stroller": False,
        },
    )
    same_node = guide_harness.client.post(
        "/api/v1/guide/routes/plan",
        json={
            "from_node_id": nodes["entrance"]["id"],
            "to_node_id": nodes["entrance"]["id"],
            "wheelchair": True,
            "stroller": True,
        },
    )

    assert direct.status_code == 200
    assert wheelchair.status_code == 200
    assert wheelchair.json()["walk_minutes"] > direct.json()["walk_minutes"]
    assert wheelchair.json()["accessible"] is True
    assert same_node.json()["walk_minutes"] == 0
    assert same_node.json()["distance_m"] == 0


def test_rules_planner_is_deterministic_and_owned(guide_harness: GuideHarness) -> None:
    token = _login(guide_harness.client, "guide_tourist_two")
    other_token = _login(guide_harness.client, "tourist_demo")
    slot = asyncio.run(_ticket_slot(guide_harness.session_factory, date_index=3))
    payload = _generate_payload(slot.visit_date.isoformat())

    first = guide_harness.client.post(
        "/api/v1/itineraries/generate",
        headers=_bearer(token),
        json=payload,
    )
    second = guide_harness.client.post(
        "/api/v1/itineraries/generate",
        headers=_bearer(token),
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["source"] == "rules"
    assert first.json()["total_score"] == second.json()["total_score"]
    assert [item["ref_id"] for item in first.json()["items"]] == [
        item["ref_id"] for item in second.json()["items"]
    ]
    assert any("no AI provider" in line for line in first.json()["explanation"])

    hidden = guide_harness.client.get(
        f"/api/v1/itineraries/{first.json()['id']}",
        headers=_bearer(other_token),
    )
    assert hidden.status_code == 404
    hidden_conflicts = guide_harness.client.post(
        f"/api/v1/itineraries/{first.json()['id']}/conflicts/check",
        headers=_bearer(other_token),
        json={"walking_buffer_minutes": 10},
    )
    hidden_replan = guide_harness.client.post(
        f"/api/v1/itineraries/{first.json()['id']}/replan",
        headers=_bearer(other_token),
        json={
            "crowd_avoidance": True,
            "preserve_locked": True,
            "expected_revision": 1,
        },
    )
    assert hidden_conflicts.status_code == 404
    assert hidden_replan.status_code == 404


def test_ticket_commitment_and_walking_buffer_conflict(guide_harness: GuideHarness) -> None:
    token = _login(guide_harness.client, "tourist_demo")
    slot = _purchase_ticket(
        guide_harness,
        token=token,
        date_index=0,
        key_prefix="guide-buffer-ticket",
    )
    generated = guide_harness.client.post(
        "/api/v1/itineraries/generate",
        headers=_bearer(token),
        json=_generate_payload(slot.visit_date.isoformat()),
    )
    assert generated.status_code == 200
    commitment = next(item for item in generated.json()["items"] if item["kind"] == "COMMITMENT")
    assert commitment["locked"] is True

    async def force_short_buffer() -> None:
        async with guide_harness.session_factory() as session:
            itinerary = await session.get(Itinerary, UUID(generated.json()["id"]))
            assert itinerary is not None
            items = list(
                await session.scalars(
                    select(ItineraryItem).where(ItineraryItem.itinerary_id == itinerary.id)
                )
            )
            locked = next(item for item in items if item.locked)
            movable = next(item for item in items if not item.locked)
            duration = movable.end_at - movable.start_at
            locked_end = locked.end_at
            if locked_end.tzinfo is None:
                locked_end = locked_end.replace(tzinfo=UTC)
            movable.start_at = locked_end + timedelta(minutes=5)
            movable.end_at = movable.start_at + duration
            await session.commit()

    asyncio.run(force_short_buffer())
    conflicts = guide_harness.client.post(
        f"/api/v1/itineraries/{generated.json()['id']}/conflicts/check",
        headers=_bearer(token),
        json={"walking_buffer_minutes": 10},
    )
    assert conflicts.status_code == 200
    assert conflicts.json()["feasible"] is False
    assert "WALK_BUFFER" in {item["code"] for item in conflicts.json()["conflicts"]}
    assert all(
        suggestion["item_id"] != commitment["id"]
        for suggestion in conflicts.json()["suggestions"]
        if suggestion["item_id"] is not None
    )


def test_high_crowd_replan_preserves_locked_and_remains_feasible(
    guide_harness: GuideHarness,
) -> None:
    token = _login(guide_harness.client, "guide_tourist_two")
    slot = _purchase_ticket(
        guide_harness,
        token=token,
        date_index=1,
        key_prefix="guide-replan-ticket",
    )
    generated = guide_harness.client.post(
        "/api/v1/itineraries/generate",
        headers=_bearer(token),
        json=_generate_payload(slot.visit_date.isoformat()),
    )
    assert generated.status_code == 200
    locked_before = next(item for item in generated.json()["items"] if item["locked"])
    unlocked_before = [item for item in generated.json()["items"] if not item["locked"]]
    assert len(unlocked_before) >= 2
    high_ref_id = UUID(unlocked_before[0]["ref_id"])

    async def persist_high_crowd() -> None:
        async with guide_harness.session_factory() as session:
            sequence = int(await session.scalar(select(func.max(CrowdSnapshot.sequence))) or 0) + 1
            attractions = list(await session.scalars(select(Attraction)))
            captured_at = datetime.now(UTC)
            for attraction in attractions:
                is_high = attraction.id == high_ref_id
                session.add(
                    CrowdSnapshot(
                        attraction_id=attraction.id,
                        crowd_level="HIGH" if is_high else "LOW",
                        occupancy_bps=9000 if is_high else 1000,
                        people_count=450 if is_high else 50,
                        wait_minutes=20 if is_high else 1,
                        source="simulated",
                        sequence=sequence,
                        observed_at=captured_at,
                    )
                )
            await session.commit()

    asyncio.run(persist_high_crowd())
    replanned = guide_harness.client.post(
        f"/api/v1/itineraries/{generated.json()['id']}/replan",
        headers=_bearer(token),
        json={
            "crowd_avoidance": True,
            "preserve_locked": True,
            "expected_revision": 1,
        },
    )
    assert replanned.status_code == 200
    assert replanned.json()["revision"] == 2
    locked_after = next(item for item in replanned.json()["items"] if item["locked"])
    assert {key: locked_after[key] for key in ("id", "ref_id", "start_at", "end_at", "locked")} == {
        key: locked_before[key] for key in ("id", "ref_id", "start_at", "end_at", "locked")
    }
    unlocked_after = [item for item in replanned.json()["items"] if not item["locked"]]
    assert [item["ref_id"] for item in unlocked_after].index(str(high_ref_id)) > 0

    conflict_check = guide_harness.client.post(
        f"/api/v1/itineraries/{generated.json()['id']}/conflicts/check",
        headers=_bearer(token),
        json={"walking_buffer_minutes": 10},
    )
    assert conflict_check.status_code == 200
    assert conflict_check.json()["feasible"] is True

    stale = guide_harness.client.post(
        f"/api/v1/itineraries/{generated.json()['id']}/replan",
        headers=_bearer(token),
        json={
            "crowd_avoidance": True,
            "preserve_locked": True,
            "expected_revision": 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVISION_CONFLICT"


def test_public_crowd_websocket_initial_and_shared_publisher_tick(
    guide_harness: GuideHarness,
) -> None:
    with guide_harness.client.websocket_connect("/api/v1/guide/ws/crowd") as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "crowd.snapshot"
        assert initial["data"]["source"] == "simulated"
        initial_sequence = initial["data"]["sequence"]

        portal = guide_harness.client.portal
        assert portal is not None
        portal.call(guide_harness.application.state.crowd_publisher.publish_once)
        updated = websocket.receive_json()
        assert updated["type"] == "crowd.snapshot"
        assert updated["data"]["sequence"] == initial_sequence + 1
        assert updated["data"]["source"] == "simulated"
        assert updated["data"]["is_demo"] is True
    assert guide_harness.application.state.crowd_hub.connection_count == 0


def test_public_crowd_websocket_rejects_mutation_messages(
    guide_harness: GuideHarness,
) -> None:
    before = guide_harness.client.get("/api/v1/guide/crowd").json()["sequence"]
    with guide_harness.client.websocket_connect("/api/v1/guide/ws/crowd") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "simulate.tick"})
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
        assert closed.value.code == 1008
    after = guide_harness.client.get("/api/v1/guide/crowd").json()["sequence"]
    assert after == before
    assert guide_harness.application.state.crowd_hub.connection_count == 0

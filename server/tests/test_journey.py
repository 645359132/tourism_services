"""Checkpoint 8 offline, sync, SOS, passport, and green-task tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.commerce import PointAccount, PointLedgerEntry
from app.db.models.guide import Itinerary
from app.db.models.journey import (
    EmergencyBulletin,
    GreenTaskCompletion,
    PassportStamp,
    SosRequest,
)
from app.db.models.role import Role, UserRole
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.scripts.seed import DEMO_PASSWORD, seed_database
from app.services.auth import get_user_by_id
from app.services.passport import check_in_stamp, complete_green_task


@dataclass(slots=True)
class JourneyHarness:
    client: TestClient
    application: FastAPI
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings


@pytest.fixture(scope="module")
def journey_harness(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[JourneyHarness]:
    database_path: Path = tmp_path_factory.mktemp("journey") / "journey.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await seed_database(session_factory, include_demo_accounts=True)
        async with session_factory() as session:
            tourist_role = await session.scalar(select(Role).where(Role.name == "tourist"))
            assert tourist_role is not None
            for username in ("journey_two", "journey_race"):
                user = User(
                    username=username,
                    display_name=username,
                    password_hash=hash_password(DEMO_PASSWORD),
                    is_active=True,
                )
                session.add(user)
                await session.flush()
                session.add(UserRole(user_id=user.id, role_id=tourist_role.id))
            await session.commit()

    asyncio.run(prepare())
    asyncio.run(engine.dispose())
    settings = Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="journey-test-jwt-secret-94a881ef46ab",
        enable_demo_accounts=True,
        crowd_publish_interval_seconds=3600,
        queue_publish_interval_seconds=3600,
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
        yield JourneyHarness(client, application, session_factory, settings)
    asyncio.run(engine.dispose())


def _login(harness: JourneyHarness, username: str) -> str:
    response = harness.client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.json()
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_offline_pack_auth_etag_304_and_asset_checksum(
    journey_harness: JourneyHarness,
) -> None:
    unauthenticated = journey_harness.client.get("/api/v1/offline/packs/latest")
    assert unauthenticated.status_code == 401
    token = _login(journey_harness, "tourist_demo")
    latest = journey_harness.client.get(
        "/api/v1/offline/packs/latest",
        headers=_bearer(token),
    )
    assert latest.status_code == 200
    pack = latest.json()
    assert pack["asset_count"] == 5
    assert pack["etag"].startswith('"') and pack["etag"].endswith('"')
    manifest_path = f"/api/v1/offline/packs/{pack['id']}/manifest"
    manifest = journey_harness.client.get(
        manifest_path,
        headers=_bearer(token),
    )
    assert manifest.status_code == 200
    assert manifest.headers["etag"] == pack["etag"]
    assert manifest.headers["cache-control"].startswith("private")
    assert manifest.headers["vary"] == "Authorization"
    assert manifest.json()["etag"] == pack["etag"]
    narration_asset = next(
        item for item in manifest.json()["assets"] if item["kind"] == "NARRATION"
    )
    not_modified = journey_harness.client.get(
        manifest_path,
        headers={
            **_bearer(token),
            "If-None-Match": pack["etag"],
        },
    )
    assert not_modified.status_code == 304
    assert not not_modified.content
    assert not_modified.headers["etag"] == pack["etag"]
    unauthenticated_304 = journey_harness.client.get(
        manifest_path,
        headers={"If-None-Match": pack["etag"]},
    )
    assert unauthenticated_304.status_code == 401

    asset = manifest.json()["assets"][0]
    content = journey_harness.client.get(
        asset["download_url"],
        headers=_bearer(token),
    )
    assert content.status_code == 200
    body = content.json()
    encoded = json.dumps(
        body["payload"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert sha256(encoded).hexdigest() == body["content_hash"]
    assert len(encoded) == body["size_bytes"]
    narration = journey_harness.client.get(
        narration_asset["download_url"],
        headers=_bearer(token),
    )
    assert narration.status_code == 200
    narration_body = narration.json()
    narration_payload = narration_body["payload"]
    narration_encoded = json.dumps(
        narration_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert sha256(narration_encoded).hexdigest() == narration_body["content_hash"]
    assert len(narration_encoded) == narration_body["size_bytes"]
    assert narration_payload["language"] == "zh-CN"
    assert narration_payload["provider_mode"] == "text_demo"
    assert narration_payload["chapters"][0]["transcript"]
    assert set(narration_payload["chapters"][0]) == {
        "code",
        "title",
        "duration_seconds",
        "transcript",
    }


def test_sync_push_pull_idempotency_pagination_and_user_bound_cursor(
    journey_harness: JourneyHarness,
) -> None:
    token = _login(journey_harness, "tourist_demo")
    other = _login(journey_harness, "journey_two")
    status = journey_harness.client.get(
        "/api/v1/offline/sync/status",
        headers=_bearer(token),
        params={"device_id": "phone-main"},
    )
    assert status.status_code == 200
    initial_cursor = status.json()["cursor"]
    payload = {
        "device_id": "phone-main",
        "base_cursor": initial_cursor,
        "mutations": [
            {
                "client_mutation_id": "note-mutation-0001",
                "client_version": 1,
                "entity_type": "NOTE",
                "entity_id": "note-1",
                "operation": "UPSERT",
                "payload": {"title": "离线笔记", "text": "入口集合"},
            },
            {
                "client_mutation_id": "note-mutation-0002",
                "client_version": 2,
                "entity_type": "NOTE",
                "entity_id": "note-2",
                "operation": "UPSERT",
                "payload": {"title": "第二条笔记", "text": "医务室位置"},
            },
        ],
    }
    pushed = journey_harness.client.post(
        "/api/v1/offline/sync/push",
        headers=_bearer(token),
        json=payload,
    )
    assert pushed.status_code == 200, pushed.json()
    assert pushed.json()["accepted"] == 2
    assert pushed.json()["replayed"] == 0
    replay = journey_harness.client.post(
        "/api/v1/offline/sync/push",
        headers=_bearer(token),
        json=payload,
    )
    assert replay.status_code == 200, replay.json()
    assert replay.json()["accepted"] == 0
    assert replay.json()["replayed"] == 2
    changed = journey_harness.client.post(
        "/api/v1/offline/sync/push",
        headers=_bearer(token),
        json={
            **payload,
            "mutations": [
                {
                    **payload["mutations"][0],
                    "payload": {"title": "changed", "text": "changed"},
                }
            ],
        },
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    first_page = journey_harness.client.get(
        "/api/v1/offline/sync/pull",
        headers=_bearer(token),
        params={"device_id": "tablet-main", "limit": 1},
    )
    assert first_page.status_code == 200
    assert first_page.json()["has_more"] is True
    assert len(first_page.json()["items"]) == 1
    second_page = journey_harness.client.get(
        "/api/v1/offline/sync/pull",
        headers=_bearer(token),
        params={
            "device_id": "tablet-main",
            "cursor": first_page.json()["next_cursor"],
            "limit": 1,
        },
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["has_more"] is False
    empty = journey_harness.client.get(
        "/api/v1/offline/sync/pull",
        headers=_bearer(token),
        params={
            "device_id": "tablet-main",
            "cursor": second_page.json()["next_cursor"],
        },
    )
    assert empty.json()["items"] == []
    cross_device = journey_harness.client.get(
        "/api/v1/offline/sync/pull",
        headers=_bearer(token),
        params={
            "device_id": "phone-main",
            "cursor": second_page.json()["next_cursor"],
        },
    )
    assert cross_device.status_code == 409
    assert cross_device.json()["error"]["code"] == "SYNC_CURSOR_INVALID"
    cross_user = journey_harness.client.get(
        "/api/v1/offline/sync/pull",
        headers=_bearer(other),
        params={
            "device_id": "other-phone",
            "cursor": second_page.json()["next_cursor"],
        },
    )
    assert cross_user.status_code == 409
    assert cross_user.json()["error"]["code"] == "SYNC_CURSOR_INVALID"

    unsafe_type = journey_harness.client.post(
        "/api/v1/offline/sync/push",
        headers=_bearer(token),
        json={
            "device_id": "phone-main",
            "mutations": [
                {
                    "client_mutation_id": "forged-stamp-0001",
                    "client_version": 3,
                    "entity_type": "PASSPORT_STAMP",
                    "entity_id": "forged",
                    "operation": "UPSERT",
                    "payload": {},
                }
            ],
        },
    )
    assert unsafe_type.status_code == 422


def test_sync_targets_owned_current_and_validated_before_cursor_allocation(
    journey_harness: JourneyHarness,
) -> None:
    token = _login(journey_harness, "tourist_demo")
    other = _login(journey_harness, "journey_two")
    itinerary_payload = {
        "visit_date": "2026-09-05",
        "start_time": "09:00:00",
        "duration_minutes": 180,
        "interests": ["history"],
        "companion_type": "solo",
        "fitness_level": "medium",
        "accessible": False,
    }
    owned = journey_harness.client.post(
        "/api/v1/itineraries/generate",
        headers=_bearer(token),
        json=itinerary_payload,
    )
    foreign = journey_harness.client.post(
        "/api/v1/itineraries/generate",
        headers=_bearer(other),
        json={**itinerary_payload, "visit_date": "2026-09-06"},
    )
    assert owned.status_code == 200, owned.json()
    assert foreign.status_code == 200, foreign.json()

    async def bump_owned_revision() -> None:
        async with journey_harness.session_factory() as session:
            await session.execute(
                update(Itinerary).where(Itinerary.id == UUID(owned.json()["id"])).values(revision=2)
            )
            await session.commit()

    asyncio.run(bump_owned_revision())
    bulletin_id = journey_harness.client.get(
        "/api/v1/emergency/bulletins",
        headers=_bearer(token),
    ).json()["items"][0]["id"]

    def push(device_id: str, mutation: dict[str, object]):
        return journey_harness.client.post(
            "/api/v1/offline/sync/push",
            headers=_bearer(token),
            json={
                "device_id": device_id,
                "mutations": [
                    {
                        "client_mutation_id": f"{device_id}-mutation-0001",
                        "client_version": 1,
                        **mutation,
                    }
                ],
            },
        )

    before_missing = journey_harness.client.get(
        "/api/v1/offline/sync/status",
        headers=_bearer(token),
        params={"device_id": "semantic-missing"},
    ).json()["server_cursor"]
    missing = push(
        "semantic-missing",
        {
            "entity_type": "ITINERARY_ACK",
            "entity_id": str(UUID(int=0)),
            "operation": "UPSERT",
            "payload": {"revision": 1},
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SYNC_TARGET_NOT_FOUND"
    after_missing = journey_harness.client.get(
        "/api/v1/offline/sync/status",
        headers=_bearer(token),
        params={"device_id": "semantic-missing"},
    ).json()["server_cursor"]
    assert after_missing == before_missing

    foreign_target = push(
        "semantic-foreign",
        {
            "entity_type": "ITINERARY_ACK",
            "entity_id": foreign.json()["id"],
            "operation": "UPSERT",
            "payload": {"revision": foreign.json()["revision"]},
        },
    )
    assert foreign_target.status_code == 404
    assert foreign_target.json()["error"]["code"] == "SYNC_TARGET_NOT_FOUND"
    stale = push(
        "semantic-stale",
        {
            "entity_type": "ITINERARY_ACK",
            "entity_id": owned.json()["id"],
            "operation": "UPSERT",
            "payload": {"revision": 1},
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "SYNC_TARGET_STALE"
    ahead = push(
        "semantic-ahead",
        {
            "entity_type": "ITINERARY_ACK",
            "entity_id": owned.json()["id"],
            "operation": "UPSERT",
            "payload": {"revision": 3},
        },
    )
    assert ahead.status_code == 409
    assert ahead.json()["error"]["code"] == "SYNC_TARGET_REVISION_INVALID"
    forbidden_delete = push(
        "semantic-delete",
        {
            "entity_type": "ITINERARY_ACK",
            "entity_id": owned.json()["id"],
            "operation": "DELETE",
            "payload": {},
        },
    )
    assert forbidden_delete.status_code == 422
    assert forbidden_delete.json()["error"]["code"] == "SYNC_DELETE_NOT_ALLOWED"
    mismatch = push(
        "semantic-mismatch",
        {
            "entity_type": "EMERGENCY_ACK",
            "entity_id": str(UUID(int=1)),
            "operation": "UPSERT",
            "payload": {
                "acknowledged": True,
                "bulletin_id": bulletin_id,
            },
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "SYNC_TARGET_MISMATCH"
    missing_bulletin_id = str(UUID(int=2))
    missing_bulletin = push(
        "semantic-bulletin-missing",
        {
            "entity_type": "EMERGENCY_ACK",
            "entity_id": missing_bulletin_id,
            "operation": "UPSERT",
            "payload": {
                "acknowledged": True,
                "bulletin_id": missing_bulletin_id,
            },
        },
    )
    assert missing_bulletin.status_code == 404
    assert missing_bulletin.json()["error"]["code"] == "SYNC_TARGET_NOT_FOUND"
    valid_itinerary = push(
        "semantic-valid-itinerary",
        {
            "entity_type": "ITINERARY_ACK",
            "entity_id": owned.json()["id"],
            "operation": "UPSERT",
            "payload": {"revision": 2},
        },
    )
    assert valid_itinerary.status_code == 200
    valid_bulletin = push(
        "semantic-valid-bulletin",
        {
            "entity_type": "EMERGENCY_ACK",
            "entity_id": bulletin_id,
            "operation": "UPSERT",
            "payload": {
                "acknowledged": True,
                "bulletin_id": bulletin_id,
            },
        },
    )
    assert valid_bulletin.status_code == 200

    async def set_bulletin_active(active: bool) -> None:
        async with journey_harness.session_factory() as session:
            await session.execute(
                update(EmergencyBulletin)
                .where(EmergencyBulletin.id == UUID(bulletin_id))
                .values(is_active=active)
            )
            await session.commit()

    asyncio.run(set_bulletin_active(False))
    inactive_bulletin = push(
        "semantic-inactive-bulletin",
        {
            "entity_type": "EMERGENCY_ACK",
            "entity_id": bulletin_id,
            "operation": "UPSERT",
            "payload": {
                "acknowledged": True,
                "bulletin_id": bulletin_id,
            },
        },
    )
    assert inactive_bulletin.status_code == 409
    assert inactive_bulletin.json()["error"]["code"] == "SYNC_TARGET_INACTIVE"
    asyncio.run(set_bulletin_active(True))


def test_sos_demo_boundary_lifecycle_rbac_and_ownership(
    journey_harness: JourneyHarness,
) -> None:
    tourist = _login(journey_harness, "tourist_demo")
    other = _login(journey_harness, "journey_two")
    support = _login(journey_harness, "support_demo")
    resources = journey_harness.client.get(
        "/api/v1/emergency/resources",
        headers=_bearer(tourist),
    )
    bulletins = journey_harness.client.get(
        "/api/v1/emergency/bulletins",
        headers=_bearer(tourist),
    )
    assert resources.status_code == 200
    assert len(resources.json()["items"]) == 3
    assert bulletins.status_code == 200
    node_id = resources.json()["items"][0]["node_id"]
    blank = journey_harness.client.post(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
        json={
            "kind": "OTHER",
            "message": "   ",
            "idempotency_key": "sos-blank-message-0001",
        },
    )
    assert blank.status_code == 422
    latitude_only = journey_harness.client.post(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
        json={
            "kind": "OTHER",
            "message": "坐标不完整",
            "latitude": 30.25,
            "idempotency_key": "sos-latitude-only-0001",
        },
    )
    assert latitude_only.status_code == 422
    longitude_only = journey_harness.client.post(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
        json={
            "kind": "OTHER",
            "message": "坐标不完整",
            "longitude": 120.15,
            "idempotency_key": "sos-longitude-only-0001",
        },
    )
    assert longitude_only.status_code == 422

    async def reject_one_sided_coordinates_in_database() -> None:
        async with journey_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            assert user_id is not None
            session.add(
                SosRequest(
                    sos_no=f"SOS-INVALID-{uuid4().hex[:12]}",
                    user_id=user_id,
                    kind="OTHER",
                    message="invalid coordinate pair",
                    status="DEMO_RECEIVED",
                    latitude_e6=30_250_000,
                    longitude_e6=None,
                    idempotency_key=f"invalid-coordinate-{uuid4().hex}",
                    request_hash="0" * 64,
                    provider="demo_sos",
                    is_demo=True,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

    asyncio.run(reject_one_sided_coordinates_in_database())
    payload = {
        "kind": "LOST",
        "message": "  与同行成员走散  ",
        "node_id": node_id,
        "latitude": 30.25,
        "longitude": 120.15,
        "idempotency_key": "sos-demo-create-0001",
    }
    created = journey_harness.client.post(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
        json=payload,
    )
    assert created.status_code == 201, created.json()
    sos = created.json()
    assert sos["status"] == "DEMO_RECEIVED"
    assert sos["message"] == "与同行成员走散"
    assert sos["provider"] == "demo_sos"
    assert sos["is_demo"] is True
    assert sos["real_dispatch"] is False
    assert "未联系真实" in sos["disclaimer"]
    replay = journey_harness.client.post(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == sos["id"]
    conflict = journey_harness.client.post(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
        json={**payload, "message": "different"},
    )
    assert conflict.status_code == 409
    hidden = journey_harness.client.get(
        f"/api/v1/emergency/sos/{sos['id']}",
        headers=_bearer(other),
    )
    assert hidden.status_code == 404
    tourist_ack = journey_harness.client.put(
        f"/api/v1/emergency/sos/{sos['id']}/acknowledge",
        headers=_bearer(tourist),
        json={},
    )
    assert tourist_ack.status_code == 403
    acknowledged = journey_harness.client.put(
        f"/api/v1/emergency/sos/{sos['id']}/acknowledge",
        headers=_bearer(support),
        json={},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"
    resolved = journey_harness.client.put(
        f"/api/v1/emergency/sos/{sos['id']}/resolve",
        headers=_bearer(support),
        json={},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    own_list = journey_harness.client.get(
        "/api/v1/emergency/sos",
        headers=_bearer(tourist),
    )
    assert [item["id"] for item in own_list.json()["items"]] == [sos["id"]]


def test_passport_and_green_duplicate_prevention_award_points_once(
    journey_harness: JourneyHarness,
) -> None:
    token = _login(journey_harness, "tourist_demo")
    before = journey_harness.client.get(
        "/api/v1/points/account",
        headers=_bearer(token),
    ).json()["balance"]
    summary = journey_harness.client.get(
        "/api/v1/passport",
        headers=_bearer(token),
    )
    assert summary.status_code == 200
    stamp = summary.json()["stamps"][0]
    first = journey_harness.client.post(
        "/api/v1/passport/check-ins",
        headers=_bearer(token),
        json={
            "stamp_code": stamp["code"],
            "idempotency_key": "passport-checkin-first-0001",
        },
    )
    assert first.status_code == 200, first.json()
    first_replay = journey_harness.client.post(
        "/api/v1/passport/check-ins",
        headers=_bearer(token),
        json={
            "stamp_code": stamp["code"],
            "idempotency_key": "passport-checkin-first-0001",
        },
    )
    assert first_replay.status_code == 200
    duplicate = journey_harness.client.post(
        "/api/v1/passport/check-ins",
        headers=_bearer(token),
        json={
            "stamp_code": stamp["code"],
            "idempotency_key": "passport-checkin-second-0001",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "PASSPORT_STAMP_ALREADY_COLLECTED"
    duplicate_replay = journey_harness.client.post(
        "/api/v1/passport/check-ins",
        headers=_bearer(token),
        json={
            "stamp_code": stamp["code"],
            "idempotency_key": "passport-checkin-second-0001",
        },
    )
    assert duplicate_replay.status_code == 409
    assert duplicate_replay.json()["error"]["code"] == "PASSPORT_STAMP_ALREADY_COLLECTED"
    rejected_key_reuse = journey_harness.client.post(
        "/api/v1/passport/check-ins",
        headers=_bearer(token),
        json={
            "stamp_code": summary.json()["stamps"][1]["code"],
            "idempotency_key": "passport-checkin-second-0001",
        },
    )
    assert rejected_key_reuse.status_code == 409
    assert rejected_key_reuse.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert first.json()["point_balance"] - before == stamp["points_award"]

    tasks = journey_harness.client.get(
        "/api/v1/green/tasks",
        headers=_bearer(token),
    )
    assert tasks.status_code == 200
    task = tasks.json()["items"][0]
    completed = journey_harness.client.post(
        f"/api/v1/green/tasks/{task['id']}/complete",
        headers=_bearer(token),
        json={
            "evidence": "游客中心公共交通接驳",
            "idempotency_key": "green-complete-first-0001",
        },
    )
    assert completed.status_code == 200, completed.json()
    completed_replay = journey_harness.client.post(
        f"/api/v1/green/tasks/{task['id']}/complete",
        headers=_bearer(token),
        json={
            "evidence": "游客中心公共交通接驳",
            "idempotency_key": "green-complete-first-0001",
        },
    )
    assert completed_replay.status_code == 200
    completed_duplicate = journey_harness.client.post(
        f"/api/v1/green/tasks/{task['id']}/complete",
        headers=_bearer(token),
        json={
            "evidence": "不同重复证据也不重复奖励",
            "idempotency_key": "green-complete-second-0001",
        },
    )
    assert completed_duplicate.status_code == 409
    assert completed_duplicate.json()["error"]["code"] == "GREEN_TASK_ALREADY_COMPLETED"
    completed_duplicate_replay = journey_harness.client.post(
        f"/api/v1/green/tasks/{task['id']}/complete",
        headers=_bearer(token),
        json={
            "evidence": "不同重复证据也不重复奖励",
            "idempotency_key": "green-complete-second-0001",
        },
    )
    assert completed_duplicate_replay.status_code == 409
    assert completed_duplicate_replay.json()["error"]["code"] == "GREEN_TASK_ALREADY_COMPLETED"
    green_rejected_key_reuse = journey_harness.client.post(
        f"/api/v1/green/tasks/{tasks.json()['items'][1]['id']}/complete",
        headers=_bearer(token),
        json={
            "evidence": "另一任务",
            "idempotency_key": "green-complete-second-0001",
        },
    )
    assert green_rejected_key_reuse.status_code == 409
    assert green_rejected_key_reuse.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    async def ledger_counts() -> tuple[int, int]:
        async with journey_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            assert user_id is not None
            passport_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.user_id == user_id,
                        PointLedgerEntry.source_type == "PASSPORT_STAMP",
                    )
                )
                or 0
            )
            green_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.user_id == user_id,
                        PointLedgerEntry.source_type == "GREEN_TASK",
                    )
                )
                or 0
            )
            return passport_count, green_count

    assert asyncio.run(ledger_counts()) == (1, 1)

    race_token = _login(journey_harness, "journey_race")
    race_summary = journey_harness.client.get(
        "/api/v1/passport",
        headers=_bearer(race_token),
    ).json()
    race_code = race_summary["stamps"][1]["code"]

    async def race_checkins() -> list[str]:
        gate = asyncio.Event()

        async def attempt(key: str) -> str:
            async with journey_harness.session_factory() as session:
                user_id = await session.scalar(
                    select(User.id).where(User.username == "journey_race")
                )
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await check_in_stamp(
                        session,
                        user=user,
                        stamp_code=race_code,
                        idempotency_key=key,
                    )
                    return "COLLECTED"
                except AppError as exc:
                    return exc.code

        tasks = [
            asyncio.create_task(attempt("race-checkin-key-one")),
            asyncio.create_task(attempt("race-checkin-key-two")),
        ]
        gate.set()
        return list(await asyncio.gather(*tasks))

    outcomes = asyncio.run(race_checkins())
    assert sorted(outcomes) == [
        "COLLECTED",
        "PASSPORT_STAMP_ALREADY_COLLECTED",
    ]
    losing_key = (
        "race-checkin-key-one"
        if outcomes[0] == "PASSPORT_STAMP_ALREADY_COLLECTED"
        else "race-checkin-key-two"
    )
    losing_key_reuse = journey_harness.client.post(
        "/api/v1/passport/check-ins",
        headers=_bearer(race_token),
        json={
            "stamp_code": race_summary["stamps"][2]["code"],
            "idempotency_key": losing_key,
        },
    )
    assert losing_key_reuse.status_code == 409
    assert losing_key_reuse.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    async def race_ledger_state() -> tuple[int, int]:
        async with journey_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "journey_race"))
            assert user_id is not None
            stamp_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PassportStamp)
                    .where(PassportStamp.user_id == user_id)
                )
                or 0
            )
            ledger_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.user_id == user_id,
                        PointLedgerEntry.source_type == "PASSPORT_STAMP",
                    )
                )
                or 0
            )
            account = await session.get(PointAccount, user_id)
            assert account is not None
            assert account.balance >= 0
            return stamp_count, ledger_count

    assert asyncio.run(race_ledger_state()) == (1, 1)


def test_concurrent_green_completion_awards_once_and_binds_loser_key(
    journey_harness: JourneyHarness,
) -> None:
    token = _login(journey_harness, "journey_two")
    tasks = journey_harness.client.get(
        "/api/v1/green/tasks",
        headers=_bearer(token),
    ).json()["items"]
    task_id = UUID(tasks[0]["id"])

    async def race_completions() -> list[str]:
        gate = asyncio.Event()

        async def attempt(key: str) -> str:
            async with journey_harness.session_factory() as session:
                user_id = await session.scalar(
                    select(User.id).where(User.username == "journey_two")
                )
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await complete_green_task(
                        session,
                        user=user,
                        task_id=task_id,
                        evidence="并发绿色任务证据",
                        idempotency_key=key,
                    )
                    return "COMPLETED"
                except AppError as exc:
                    return exc.code

        tasks = [
            asyncio.create_task(attempt("green-race-key-one")),
            asyncio.create_task(attempt("green-race-key-two")),
        ]
        gate.set()
        return list(await asyncio.gather(*tasks))

    outcomes = asyncio.run(race_completions())
    assert sorted(outcomes) == ["COMPLETED", "GREEN_TASK_ALREADY_COMPLETED"]
    losing_key = (
        "green-race-key-one"
        if outcomes[0] == "GREEN_TASK_ALREADY_COMPLETED"
        else "green-race-key-two"
    )
    losing_key_reuse = journey_harness.client.post(
        f"/api/v1/green/tasks/{tasks[1]['id']}/complete",
        headers=_bearer(token),
        json={
            "evidence": "另一绿色任务",
            "idempotency_key": losing_key,
        },
    )
    assert losing_key_reuse.status_code == 409
    assert losing_key_reuse.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    async def persisted_state() -> tuple[int, int]:
        async with journey_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "journey_two"))
            assert user_id is not None
            completion_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(GreenTaskCompletion)
                    .where(
                        GreenTaskCompletion.user_id == user_id,
                        GreenTaskCompletion.task_id == task_id,
                    )
                )
                or 0
            )
            ledger_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.user_id == user_id,
                        PointLedgerEntry.source_type == "GREEN_TASK",
                    )
                )
                or 0
            )
            return completion_count, ledger_count

    assert asyncio.run(persisted_state()) == (1, 1)

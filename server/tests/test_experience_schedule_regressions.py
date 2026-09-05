"""Regression tests for hard conflicts in project and performance reservations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.marketplace import (
    Experience,
    ExperienceSession,
    InventoryBucket,
    UserScheduleLock,
)
from app.db.models.role import Role, UserRole
from app.db.models.ticketing import TicketSlot
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.scripts.seed import DEMO_PASSWORD, seed_database


@dataclass(slots=True)
class ScheduleHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture(scope="module")
def schedule_harness(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ScheduleHarness]:
    database_path: Path = tmp_path_factory.mktemp("experience-schedule") / "schedule.db"
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
            for username in ("schedule_ticket_holder", "schedule_adjacent"):
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
        jwt_secret_key="experience-schedule-regression-secret",
        enable_demo_accounts=True,
        crowd_publish_interval_seconds=3600,
        queue_publish_interval_seconds=3600,
        reservation_walking_buffer_minutes=10,
        log_level="CRITICAL",
    )
    application: FastAPI = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    application.state.crowd_publisher.session_factory_provider = lambda: session_factory
    application.state.queue_publisher.session_factory_provider = lambda: session_factory
    with TestClient(application) as client:
        yield ScheduleHarness(client=client, session_factory=session_factory)
    asyncio.run(engine.dispose())


def _bearer(harness: ScheduleHarness, username: str) -> dict[str, str]:
    response = harness.client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _visit_date() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)


async def _seeded_schedule_ids(
    harness: ScheduleHarness,
) -> tuple[UUID, UUID, UUID, UUID]:
    visit_date = _visit_date()
    async with harness.session_factory() as session:
        ticket_slot = await session.scalar(
            select(TicketSlot)
            .where(TicketSlot.visit_date == visit_date)
            .order_by(TicketSlot.start_time)
        )
        heritage = await session.scalar(
            select(Experience).where(Experience.code == "heritage_show")
        )
        boat = await session.scalar(select(Experience).where(Experience.code == "lake_boat"))
        assert ticket_slot is not None and heritage is not None and boat is not None
        heritage_session = await session.scalar(
            select(ExperienceSession)
            .where(ExperienceSession.experience_id == heritage.id)
            .order_by(ExperienceSession.starts_at)
        )
        overlapping_boat = await session.scalar(
            select(ExperienceSession)
            .where(
                ExperienceSession.experience_id == boat.id,
                ExperienceSession.starts_at == heritage_session.starts_at,
            )
        )
        assert heritage_session is not None and overlapping_boat is not None

        # A second session starts exactly when the show ends. Under [start, end)
        # these are adjacent, while the old transaction rule rejected it solely
        # because a planning-only ten-minute walking buffer leaked into checkout.
        adjacent_session = await session.scalar(
            select(ExperienceSession).where(
                ExperienceSession.experience_id == boat.id,
                ExperienceSession.starts_at == heritage_session.ends_at,
            )
        )
        if adjacent_session is None:
            adjacent_session = ExperienceSession(
                experience_id=boat.id,
                starts_at=heritage_session.ends_at,
                ends_at=heritage_session.ends_at + timedelta(minutes=boat.duration_minutes),
                capacity=24,
                status="OPEN",
            )
            session.add(adjacent_session)
            await session.flush()
            session.add(
                InventoryBucket(
                    resource_type="EXPERIENCE_SESSION",
                    resource_id=adjacent_session.id,
                    business_date=visit_date,
                    starts_at=adjacent_session.starts_at,
                    ends_at=adjacent_session.ends_at,
                    capacity=24,
                    held=0,
                    confirmed=0,
                )
            )
            await session.commit()
        return ticket_slot.id, heritage_session.id, overlapping_boat.id, adjacent_session.id


def test_admission_ticket_does_not_block_an_in_park_performance(
    schedule_harness: ScheduleHarness,
) -> None:
    ticket_slot_id, show_session_id, _, _ = asyncio.run(_seeded_schedule_ids(schedule_harness))
    headers = _bearer(schedule_harness, "schedule_ticket_holder")
    quote = schedule_harness.client.post(
        "/api/v1/ticketing/quotes",
        json={"slot_id": str(ticket_slot_id), "quantity": 1},
    )
    assert quote.status_code == 200
    ticket = schedule_harness.client.post(
        "/api/v1/ticketing/orders",
        headers=headers,
        json={
            "slot_id": str(ticket_slot_id),
            "quantity": 1,
            "quote_token": quote.json()["quote_token"],
            "idempotency_key": "schedule-ticket-holder-order",
        },
    )
    assert ticket.status_code == 201, ticket.json()

    performance = schedule_harness.client.post(
        "/api/v1/reservations",
        headers=headers,
        json={
            "session_id": str(show_session_id),
            "party_size": 1,
            "idempotency_key": "schedule-ticket-holder-show",
        },
    )
    assert performance.status_code == 201, performance.json()


def test_only_real_overlap_blocks_another_experience(
    schedule_harness: ScheduleHarness,
) -> None:
    _, show_session_id, overlapping_session_id, adjacent_session_id = asyncio.run(
        _seeded_schedule_ids(schedule_harness)
    )
    headers = _bearer(schedule_harness, "schedule_adjacent")
    first = schedule_harness.client.post(
        "/api/v1/reservations",
        headers=headers,
        json={
            "session_id": str(show_session_id),
            "party_size": 1,
            "idempotency_key": "schedule-first-show",
        },
    )
    assert first.status_code == 201, first.json()

    overlapping = schedule_harness.client.post(
        "/api/v1/reservations",
        headers=headers,
        json={
            "session_id": str(overlapping_session_id),
            "party_size": 1,
            "idempotency_key": "schedule-overlap-boat",
        },
    )
    assert overlapping.status_code == 409
    assert overlapping.json()["error"]["code"] == "SCHEDULE_CONFLICT"

    adjacent = schedule_harness.client.post(
        "/api/v1/reservations",
        headers=headers,
        json={
            "session_id": str(adjacent_session_id),
            "party_size": 1,
            "idempotency_key": "schedule-adjacent-boat",
        },
    )
    assert adjacent.status_code == 201, adjacent.json()

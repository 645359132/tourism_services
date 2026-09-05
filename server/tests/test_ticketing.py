"""End-to-end ticketing inventory, lifecycle, QR, and authorization tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.role import Role, UserRole
from app.db.models.ticketing import (
    TICKET_ISSUED,
    ElectronicTicket,
    TicketInventory,
    TicketOrder,
    TicketOrderItem,
    TicketSlot,
    TicketType,
)
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.scripts.seed import DEMO_PASSWORD, seed_database
from app.services.ticketing import create_ticket_order


@dataclass(slots=True)
class TicketingHarness:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings
    database_path: Path
    gate_slot_id: UUID


@pytest.fixture(scope="module")
def ticketing_harness(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TicketingHarness]:
    database_path = tmp_path_factory.mktemp("ticketing") / "ticketing.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare_database() -> UUID:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await seed_database(session_factory, include_demo_accounts=True)

        async with session_factory() as session:
            tourist_role = await session.scalar(select(Role).where(Role.name == "tourist"))
            adult_type = await session.scalar(select(TicketType).where(TicketType.code == "adult"))
            assert tourist_role is not None
            assert adult_type is not None

            second_tourist = User(
                username="tourist_two",
                display_name="Second Tourist",
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            session.add(second_tourist)
            await session.flush()
            session.add(UserRole(user_id=second_tourist.id, role_id=tourist_role.id))

            scenic_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            gate_slot = TicketSlot(
                ticket_type_id=adult_type.id,
                visit_date=scenic_today,
                start_time=time(0, 0),
                end_time=time(23, 59, 59),
                is_active=True,
            )
            gate_slot.inventory = TicketInventory(capacity=10, reserved=0, sold=0)
            session.add(gate_slot)
            await session.commit()
            return gate_slot.id

    gate_slot_id = asyncio.run(prepare_database())
    asyncio.run(engine.dispose())

    settings = Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="ticketing-test-secret-6ca3c4bbf77845d1",
        enable_demo_accounts=True,
        log_level="CRITICAL",
    )
    application = create_app(settings)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    with TestClient(application) as client:
        yield TicketingHarness(
            client=client,
            session_factory=session_factory,
            settings=settings,
            database_path=database_path,
            gate_slot_id=gate_slot_id,
        )
    asyncio.run(engine.dispose())


def _login(client: TestClient, username: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


def _bearer(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_order(
    harness: TicketingHarness,
    *,
    token: object,
    slot_id: UUID | str,
    quantity: int,
    key: str,
):
    return harness.client.post(
        "/api/v1/ticketing/orders",
        headers=_bearer(token),
        json={
            "slot_id": str(slot_id),
            "quantity": quantity,
            "idempotency_key": key,
        },
    )


def _pay_order(
    harness: TicketingHarness,
    *,
    token: object,
    order_id: str,
    key: str,
):
    return harness.client.post(
        f"/api/v1/ticketing/orders/{order_id}/pay",
        headers=_bearer(token),
        json={"idempotency_key": key},
    )


def test_demo_refund_cutoff_defaults_to_two_hours(
    ticketing_harness: TicketingHarness,
) -> None:
    assert ticketing_harness.settings.ticket_refund_cutoff_hours == 2


def test_order_response_exposes_runtime_refund_policy(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_two")["access_token"]

    async def create_policy_slot() -> tuple[UUID, datetime]:
        async with ticketing_harness.session_factory() as session:
            adult_type = await session.scalar(
                select(TicketType).where(TicketType.code == "adult")
            )
            assert adult_type is not None
            visit_date = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=75)
            slot = TicketSlot(
                ticket_type_id=adult_type.id,
                visit_date=visit_date,
                start_time=time(10, 0),
                end_time=time(11, 0),
                is_active=True,
            )
            slot.inventory = TicketInventory(capacity=3, reserved=0, sold=0)
            session.add(slot)
            await session.commit()
            start_at = datetime.combine(
                visit_date,
                time(10, 0),
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ).astimezone(ZoneInfo("UTC"))
            return slot.id, start_at

    slot_id, starts_at = asyncio.run(create_policy_slot())
    original_cutoff = ticketing_harness.settings.ticket_refund_cutoff_hours
    ticketing_harness.settings.ticket_refund_cutoff_hours = 6
    try:
        created = _create_order(
            ticketing_harness,
            token=token,
            slot_id=slot_id,
            quantity=1,
            key="refund-policy-create-001",
        )
        paid = _pay_order(
            ticketing_harness,
            token=token,
            order_id=created.json()["id"],
            key="refund-policy-payment-001",
        )
    finally:
        ticketing_harness.settings.ticket_refund_cutoff_hours = original_cutoff

    assert created.status_code == 201
    assert created.json()["refund_cutoff_hours"] == 6
    assert created.json()["refundable"] is False
    assert paid.status_code == 200
    assert paid.json()["refund_cutoff_hours"] == 6
    assert paid.json()["refundable"] is True
    deadline = datetime.fromisoformat(paid.json()["refund_deadline_at"])
    assert deadline == starts_at - timedelta(hours=6)
    assert deadline.utcoffset() == timedelta(0)


def test_dynamic_weekend_and_occupancy_pricing(ticketing_harness: TicketingHarness) -> None:
    async def select_weekend_slot() -> UUID:
        async with ticketing_harness.session_factory() as session:
            adult_type = await session.scalar(select(TicketType).where(TicketType.code == "adult"))
            assert adult_type is not None
            slots = list(
                await session.scalars(
                    select(TicketSlot)
                    .where(
                        TicketSlot.ticket_type_id == adult_type.id,
                        TicketSlot.id != ticketing_harness.gate_slot_id,
                    )
                    .order_by(TicketSlot.visit_date, TicketSlot.start_time)
                )
            )
            slot = next(candidate for candidate in slots if candidate.visit_date.weekday() >= 5)
            return slot.id

    slot_id = asyncio.run(select_weekend_slot())
    weekend_quote = ticketing_harness.client.post(
        "/api/v1/ticketing/quotes",
        json={"slot_id": str(slot_id), "quantity": 2},
    )
    assert weekend_quote.status_code == 200
    assert weekend_quote.json()["unit_price_cents"] == 14_400

    async def raise_occupancy() -> None:
        async with ticketing_harness.session_factory() as session:
            await session.execute(
                update(TicketInventory)
                .where(TicketInventory.slot_id == slot_id)
                .values(reserved=70)
            )
            await session.commit()

    asyncio.run(raise_occupancy())
    occupied_quote = ticketing_harness.client.post(
        "/api/v1/ticketing/quotes",
        json={"slot_id": str(slot_id), "quantity": 1},
    )
    assert occupied_quote.status_code == 200
    assert occupied_quote.json()["unit_price_cents"] == 16_200
    assert len(occupied_quote.json()["pricing_explanation"]) == 3


def test_client_amount_is_forbidden_and_cannot_change_server_price(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]
    response = ticketing_harness.client.post(
        "/api/v1/ticketing/orders",
        headers=_bearer(token),
        json={
            "slot_id": str(ticketing_harness.gate_slot_id),
            "quantity": 1,
            "idempotency_key": "amount-forbid-001",
            "total_cents": 1,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_capacity_one_concurrent_orders_never_oversell(
    ticketing_harness: TicketingHarness,
) -> None:
    async def prepare_capacity_one() -> tuple[UUID, UUID, UUID]:
        async with ticketing_harness.session_factory() as session:
            family_type = await session.scalar(
                select(TicketType).where(TicketType.code == "family")
            )
            tourist = await session.scalar(select(User).where(User.username == "tourist_demo"))
            second = await session.scalar(select(User).where(User.username == "tourist_two"))
            assert family_type is not None and tourist is not None and second is not None
            slot = await session.scalar(
                select(TicketSlot)
                .where(TicketSlot.ticket_type_id == family_type.id)
                .order_by(TicketSlot.visit_date.desc(), TicketSlot.start_time.desc())
            )
            assert slot is not None
            await session.execute(
                update(TicketInventory)
                .where(TicketInventory.slot_id == slot.id)
                .values(capacity=1, reserved=0, sold=0)
            )
            await session.commit()
            return slot.id, tourist.id, second.id

    slot_id, first_user_id, second_user_id = asyncio.run(prepare_capacity_one())

    async def race() -> list[str]:
        async def attempt(user_id: UUID, key: str) -> str:
            async with ticketing_harness.session_factory() as session:
                user = await session.get(User, user_id)
                assert user is not None
                try:
                    order = await create_ticket_order(
                        session,
                        user=user,
                        slot_id=slot_id,
                        quantity=1,
                        idempotency_key=key,
                        settings=ticketing_harness.settings,
                    )
                    return str(order.id)
                except AppError as exc:
                    return exc.code

        return list(
            await asyncio.gather(
                attempt(first_user_id, "capacity-race-001"),
                attempt(second_user_id, "capacity-race-002"),
            )
        )

    outcomes = asyncio.run(race())
    assert outcomes.count("INSUFFICIENT_INVENTORY") == 1
    assert sum(outcome != "INSUFFICIENT_INVENTORY" for outcome in outcomes) == 1

    async def ledger() -> tuple[int, int, int]:
        async with ticketing_harness.session_factory() as session:
            inventory = await session.get(TicketInventory, slot_id)
            assert inventory is not None
            return inventory.capacity, inventory.reserved, inventory.sold

    assert asyncio.run(ledger()) == (1, 1, 0)


def test_order_create_idempotency_and_payload_conflict(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]
    first = _create_order(
        ticketing_harness,
        token=token,
        slot_id=ticketing_harness.gate_slot_id,
        quantity=1,
        key="create-idempotency-001",
    )
    replay = _create_order(
        ticketing_harness,
        token=token,
        slot_id=ticketing_harness.gate_slot_id,
        quantity=1,
        key="create-idempotency-001",
    )
    conflict = _create_order(
        ticketing_harness,
        token=token,
        slot_id=ticketing_harness.gate_slot_id,
        quantity=2,
        key="create-idempotency-001",
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_payment_qr_and_single_gate_validation(ticketing_harness: TicketingHarness) -> None:
    tourist_tokens = _login(ticketing_harness.client, "tourist_demo")
    admin_tokens = _login(ticketing_harness.client, "admin_demo")
    created = _create_order(
        ticketing_harness,
        token=tourist_tokens["access_token"],
        slot_id=ticketing_harness.gate_slot_id,
        quantity=1,
        key="gate-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=tourist_tokens["access_token"],
        order_id=created.json()["id"],
        key="gate-payment-001",
    )

    assert paid.status_code == 200
    assert paid.json()["status"] == "PAID"
    assert paid.json()["tickets"][0]["status"] == "ISSUED"
    payment_replay = _pay_order(
        ticketing_harness,
        token=tourist_tokens["access_token"],
        order_id=created.json()["id"],
        key="gate-payment-001",
    )
    assert payment_replay.status_code == 200
    assert payment_replay.json()["tickets"] == paid.json()["tickets"]
    ticket_id = paid.json()["tickets"][0]["id"]

    qr = ticketing_harness.client.get(
        f"/api/v1/ticketing/tickets/{ticket_id}/qr",
        headers=_bearer(tourist_tokens["access_token"]),
    )
    assert qr.status_code == 200
    assert qr.headers["Cache-Control"] == "no-store"
    assert qr.headers["Pragma"] == "no-cache"
    assert "tourist_demo" not in qr.json()["qr_data"]
    assert datetime.fromisoformat(qr.json()["expires_at"]).utcoffset() == timedelta(0)

    tourist_forbidden = ticketing_harness.client.post(
        "/api/v1/ticketing/gate/validate",
        headers=_bearer(tourist_tokens["access_token"]),
        json={
            "qr_data": qr.json()["qr_data"],
            "request_id": "gate-request-001",
            "gate_code": "north-gate",
        },
    )
    assert tourist_forbidden.status_code == 403

    accepted = ticketing_harness.client.post(
        "/api/v1/ticketing/gate/validate",
        headers=_bearer(admin_tokens["access_token"]),
        json={
            "qr_data": qr.json()["qr_data"],
            "request_id": "gate-request-001",
            "gate_code": "north-gate",
        },
    )
    replay = ticketing_harness.client.post(
        "/api/v1/ticketing/gate/validate",
        headers=_bearer(admin_tokens["access_token"]),
        json={
            "qr_data": qr.json()["qr_data"],
            "request_id": "gate-request-001",
            "gate_code": "north-gate",
        },
    )
    second_scan = ticketing_harness.client.post(
        "/api/v1/ticketing/gate/validate",
        headers=_bearer(admin_tokens["access_token"]),
        json={
            "qr_data": qr.json()["qr_data"],
            "request_id": "gate-request-002",
            "gate_code": "north-gate",
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["result"] == "ACCEPTED"
    assert datetime.fromisoformat(accepted.json()["validated_at"]).utcoffset() == timedelta(0)
    assert replay.status_code == 200
    assert datetime.fromisoformat(replay.json()["validated_at"]).utcoffset() == timedelta(0)
    assert replay.json()["validation_id"] == accepted.json()["validation_id"]
    assert second_scan.status_code == 409


def test_refund_voids_tickets_and_replenishes_sold_inventory(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def far_future_child_slot() -> UUID:
        async with ticketing_harness.session_factory() as session:
            child_type = await session.scalar(select(TicketType).where(TicketType.code == "child"))
            assert child_type is not None
            slot = await session.scalar(
                select(TicketSlot)
                .where(TicketSlot.ticket_type_id == child_type.id)
                .order_by(TicketSlot.visit_date.desc(), TicketSlot.start_time.desc())
            )
            assert slot is not None
            return slot.id

    slot_id = asyncio.run(far_future_child_slot())
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=slot_id,
        quantity=2,
        key="refund-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=token,
        order_id=created.json()["id"],
        key="refund-payment-001",
    )
    assert paid.status_code == 200

    refunded = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/refund",
        headers=_bearer(token),
        json={"reason": "Travel plans changed", "idempotency_key": "refund-request-001"},
    )
    replay = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/refund",
        headers=_bearer(token),
        json={"reason": "Travel plans changed", "idempotency_key": "refund-request-001"},
    )

    assert refunded.status_code == 200
    assert refunded.json()["status"] == "REFUNDED"
    assert {ticket["status"] for ticket in refunded.json()["tickets"]} == {"VOID"}
    assert replay.status_code == 200

    async def sold_count() -> int:
        async with ticketing_harness.session_factory() as session:
            inventory = await session.get(TicketInventory, slot_id)
            assert inventory is not None
            return inventory.sold

    assert asyncio.run(sold_count()) == 0


def test_pending_order_can_be_cancelled_idempotently_and_releases_reserved_inventory(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def create_cancel_slot() -> tuple[UUID, str, UUID]:
        async with ticketing_harness.session_factory() as session:
            adult_type = await session.scalar(
                select(TicketType).where(TicketType.code == "adult")
            )
            assert adult_type is not None
            visit_date = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=60)
            slot = TicketSlot(
                ticket_type_id=adult_type.id,
                visit_date=visit_date,
                start_time=time(9, 0),
                end_time=time(12, 0),
                is_active=True,
            )
            slot.inventory = TicketInventory(capacity=5, reserved=0, sold=0)
            session.add(slot)
            await session.commit()
            return slot.id, visit_date.isoformat(), adult_type.id

    slot_id, visit_date, ticket_type_id = asyncio.run(create_cancel_slot())

    def remaining() -> int:
        response = ticketing_harness.client.get(
            "/api/v1/ticketing/slots",
            params={"visit_date": visit_date, "ticket_type_id": str(ticket_type_id)},
        )
        assert response.status_code == 200
        slot = next(item for item in response.json()["items"] if item["id"] == str(slot_id))
        return int(slot["remaining"])

    assert remaining() == 5
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=slot_id,
        quantity=2,
        key="cancel-create-001",
    )
    assert created.status_code == 201
    assert created.json()["status"] == "PENDING_PAYMENT"
    assert datetime.fromisoformat(created.json()["expires_at"]).utcoffset() == timedelta(0)
    assert remaining() == 3

    cancelled = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/cancel",
        headers=_bearer(token),
        json={"idempotency_key": "cancel-request-001"},
    )
    replay = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/cancel",
        headers=_bearer(token),
        json={"idempotency_key": "cancel-request-001"},
    )
    resource_replay = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/cancel",
        headers=_bearer(token),
        json={"idempotency_key": "cancel-request-002"},
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert replay.status_code == 200
    assert replay.json()["id"] == cancelled.json()["id"]
    assert resource_replay.status_code == 200
    assert resource_replay.json()["id"] == cancelled.json()["id"]
    assert remaining() == 5


def test_failed_reschedule_rolls_back_target_and_source_ledgers(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def create_test_slots() -> tuple[UUID, UUID]:
        async with ticketing_harness.session_factory() as session:
            student_type = await session.scalar(
                select(TicketType).where(TicketType.code == "student")
            )
            assert student_type is not None
            visit_date = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=10)
            source = TicketSlot(
                ticket_type_id=student_type.id,
                visit_date=visit_date,
                start_time=time(8, 0),
                end_time=time(9, 0),
                is_active=True,
            )
            source.inventory = TicketInventory(capacity=100, reserved=70, sold=0)
            target = TicketSlot(
                ticket_type_id=student_type.id,
                visit_date=visit_date,
                start_time=time(9, 0),
                end_time=time(10, 0),
                is_active=True,
            )
            target.inventory = TicketInventory(capacity=1, reserved=0, sold=1)
            session.add_all([source, target])
            await session.commit()
            return source.id, target.id

    source_id, target_id = asyncio.run(create_test_slots())
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=source_id,
        quantity=1,
        key="reschedule-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=token,
        order_id=created.json()["id"],
        key="reschedule-payment-001",
    )
    assert paid.status_code == 200

    failed = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/reschedule",
        headers=_bearer(token),
        json={
            "target_slot_id": str(target_id),
            "idempotency_key": "reschedule-request-001",
        },
    )
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "INSUFFICIENT_INVENTORY"

    async def ledger_and_order() -> tuple[int, int, UUID, str]:
        async with ticketing_harness.session_factory() as session:
            source_inventory = await session.get(TicketInventory, source_id)
            target_inventory = await session.get(TicketInventory, target_id)
            item = await session.scalar(
                select(TicketOrderItem).where(
                    TicketOrderItem.order_id == UUID(created.json()["id"])
                )
            )
            ticket_status = await session.scalar(
                select(ElectronicTicket.status).where(
                    ElectronicTicket.order_id == UUID(created.json()["id"])
                )
            )
            assert source_inventory is not None and target_inventory is not None
            assert item is not None and ticket_status is not None
            return source_inventory.sold, target_inventory.sold, item.slot_id, ticket_status

    assert asyncio.run(ledger_and_order()) == (1, 1, source_id, TICKET_ISSUED)


def test_successful_reschedule_swaps_inventory_and_ticket_credentials(
    ticketing_harness: TicketingHarness,
) -> None:
    tourist_tokens = _login(ticketing_harness.client, "tourist_demo")
    admin_tokens = _login(ticketing_harness.client, "admin_demo")

    async def create_current_slots() -> tuple[UUID, UUID]:
        async with ticketing_harness.session_factory() as session:
            adult_type = await session.scalar(select(TicketType).where(TicketType.code == "adult"))
            assert adult_type is not None
            scenic_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            source = TicketSlot(
                ticket_type_id=adult_type.id,
                visit_date=scenic_today,
                start_time=time(0, 1),
                end_time=time(23, 58),
                is_active=True,
            )
            source.inventory = TicketInventory(capacity=5, reserved=0, sold=0)
            target = TicketSlot(
                ticket_type_id=adult_type.id,
                visit_date=scenic_today,
                start_time=time(0, 2),
                end_time=time(23, 57),
                is_active=True,
            )
            target.inventory = TicketInventory(capacity=5, reserved=0, sold=0)
            session.add_all([source, target])
            await session.commit()
            return source.id, target.id

    source_id, target_id = asyncio.run(create_current_slots())
    created = _create_order(
        ticketing_harness,
        token=tourist_tokens["access_token"],
        slot_id=source_id,
        quantity=1,
        key="reschedule-success-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=tourist_tokens["access_token"],
        order_id=created.json()["id"],
        key="reschedule-success-payment-001",
    )
    old_ticket_id = paid.json()["tickets"][0]["id"]
    old_qr = ticketing_harness.client.get(
        f"/api/v1/ticketing/tickets/{old_ticket_id}/qr",
        headers=_bearer(tourist_tokens["access_token"]),
    )
    assert old_qr.status_code == 200

    rescheduled = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/reschedule",
        headers=_bearer(tourist_tokens["access_token"]),
        json={
            "target_slot_id": str(target_id),
            "idempotency_key": "reschedule-success-request-001",
        },
    )
    assert rescheduled.status_code == 200
    body = rescheduled.json()
    assert body["slot_id"] == str(target_id)
    assert {ticket["status"] for ticket in body["tickets"]} == {"ISSUED", "VOID"}
    new_ticket = next(ticket for ticket in body["tickets"] if ticket["status"] == "ISSUED")

    old_rejected = ticketing_harness.client.post(
        "/api/v1/ticketing/gate/validate",
        headers=_bearer(admin_tokens["access_token"]),
        json={
            "qr_data": old_qr.json()["qr_data"],
            "request_id": "old-rescheduled-qr-001",
            "gate_code": "east-gate",
        },
    )
    assert old_rejected.status_code == 409

    new_qr = ticketing_harness.client.get(
        f"/api/v1/ticketing/tickets/{new_ticket['id']}/qr",
        headers=_bearer(tourist_tokens["access_token"]),
    )
    accepted = ticketing_harness.client.post(
        "/api/v1/ticketing/gate/validate",
        headers=_bearer(admin_tokens["access_token"]),
        json={
            "qr_data": new_qr.json()["qr_data"],
            "request_id": "new-rescheduled-qr-001",
            "gate_code": "east-gate",
        },
    )
    assert new_qr.status_code == 200
    assert accepted.status_code == 200

    async def ledger() -> tuple[int, int]:
        async with ticketing_harness.session_factory() as session:
            source = await session.get(TicketInventory, source_id)
            target = await session.get(TicketInventory, target_id)
            assert source is not None and target is not None
            return source.sold, target.sold

    assert asyncio.run(ledger()) == (0, 1)


def test_reschedule_price_delta_is_rejected_without_ledger_changes(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def create_price_delta_slots() -> tuple[UUID, UUID]:
        async with ticketing_harness.session_factory() as session:
            child_type = await session.scalar(select(TicketType).where(TicketType.code == "child"))
            assert child_type is not None
            visit_date = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=20)
            source = TicketSlot(
                ticket_type_id=child_type.id,
                visit_date=visit_date,
                start_time=time(8, 0),
                end_time=time(9, 0),
                is_active=True,
            )
            source.inventory = TicketInventory(capacity=100, reserved=0, sold=0)
            target = TicketSlot(
                ticket_type_id=child_type.id,
                visit_date=visit_date,
                start_time=time(9, 0),
                end_time=time(10, 0),
                is_active=True,
            )
            target.inventory = TicketInventory(capacity=100, reserved=70, sold=0)
            session.add_all([source, target])
            await session.commit()
            return source.id, target.id

    source_id, target_id = asyncio.run(create_price_delta_slots())
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=source_id,
        quantity=1,
        key="price-delta-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=token,
        order_id=created.json()["id"],
        key="price-delta-payment-001",
    )
    assert paid.status_code == 200

    failed = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/reschedule",
        headers=_bearer(token),
        json={
            "target_slot_id": str(target_id),
            "idempotency_key": "price-delta-request-001",
        },
    )
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "RESCHEDULE_PRICE_DELTA_UNSUPPORTED"

    async def ledger() -> tuple[int, int, int, int]:
        async with ticketing_harness.session_factory() as session:
            source = await session.get(TicketInventory, source_id)
            target = await session.get(TicketInventory, target_id)
            assert source is not None and target is not None
            return source.reserved, source.sold, target.reserved, target.sold

    assert asyncio.run(ledger()) == (0, 1, 70, 0)


def test_successful_reschedule_refreshes_response_visit_date(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def create_different_date_slots() -> tuple[UUID, UUID, str]:
        async with ticketing_harness.session_factory() as session:
            student_type = await session.scalar(
                select(TicketType).where(TicketType.code == "student")
            )
            assert student_type is not None
            source_date = datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=14)
            target_date = source_date + timedelta(days=7)
            source = TicketSlot(
                ticket_type_id=student_type.id,
                visit_date=source_date,
                start_time=time(13, 0),
                end_time=time(14, 0),
                is_active=True,
            )
            source.inventory = TicketInventory(capacity=5, reserved=0, sold=0)
            target = TicketSlot(
                ticket_type_id=student_type.id,
                visit_date=target_date,
                start_time=time(13, 0),
                end_time=time(14, 0),
                is_active=True,
            )
            target.inventory = TicketInventory(capacity=5, reserved=0, sold=0)
            session.add_all([source, target])
            await session.commit()
            return source.id, target.id, target_date.isoformat()

    source_id, target_id, target_date = asyncio.run(create_different_date_slots())
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=source_id,
        quantity=1,
        key="date-reschedule-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=token,
        order_id=created.json()["id"],
        key="date-reschedule-payment-001",
    )
    assert paid.status_code == 200

    rescheduled = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/reschedule",
        headers=_bearer(token),
        json={
            "target_slot_id": str(target_id),
            "idempotency_key": "date-reschedule-request-001",
        },
    )
    assert rescheduled.status_code == 200
    assert rescheduled.json()["slot_id"] == str(target_id)
    assert rescheduled.json()["visit_date"] == target_date


def test_used_ticket_refund_is_rejected_without_inventory_replenishment(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def create_refund_slot() -> UUID:
        async with ticketing_harness.session_factory() as session:
            family_type = await session.scalar(
                select(TicketType).where(TicketType.code == "family")
            )
            assert family_type is not None
            slot = TicketSlot(
                ticket_type_id=family_type.id,
                visit_date=datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=30),
                start_time=time(10, 0),
                end_time=time(11, 0),
                is_active=True,
            )
            slot.inventory = TicketInventory(capacity=5, reserved=0, sold=0)
            session.add(slot)
            await session.commit()
            return slot.id

    slot_id = asyncio.run(create_refund_slot())
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=slot_id,
        quantity=1,
        key="used-refund-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=token,
        order_id=created.json()["id"],
        key="used-refund-payment-001",
    )
    ticket_id = UUID(paid.json()["tickets"][0]["id"])

    async def mark_used() -> None:
        async with ticketing_harness.session_factory() as session:
            await session.execute(
                update(ElectronicTicket)
                .where(ElectronicTicket.id == ticket_id)
                .values(status="USED", used_at=datetime.now(ZoneInfo("UTC")))
            )
            await session.commit()

    asyncio.run(mark_used())
    rejected = ticketing_harness.client.post(
        f"/api/v1/ticketing/orders/{created.json()['id']}/refund",
        headers=_bearer(token),
        json={
            "reason": "Should not refund used ticket",
            "idempotency_key": "used-refund-request-001",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "TICKET_ALREADY_USED"

    async def sold() -> int:
        async with ticketing_harness.session_factory() as session:
            inventory = await session.get(TicketInventory, slot_id)
            assert inventory is not None
            return inventory.sold

    assert asyncio.run(sold()) == 1


def test_order_ownership_and_role_authorization(ticketing_harness: TicketingHarness) -> None:
    first_token = _login(ticketing_harness.client, "tourist_demo")["access_token"]
    second_token = _login(ticketing_harness.client, "tourist_two")["access_token"]
    merchant_token = _login(ticketing_harness.client, "merchant_demo")["access_token"]
    created = _create_order(
        ticketing_harness,
        token=first_token,
        slot_id=ticketing_harness.gate_slot_id,
        quantity=1,
        key="ownership-create-001",
    )

    hidden = ticketing_harness.client.get(
        f"/api/v1/ticketing/orders/{created.json()['id']}",
        headers=_bearer(second_token),
    )
    role_forbidden = ticketing_harness.client.get(
        "/api/v1/ticketing/orders",
        headers=_bearer(merchant_token),
    )

    assert hidden.status_code == 404
    assert role_forbidden.status_code == 403


def test_order_pagination_filters_owner_before_limit(
    ticketing_harness: TicketingHarness,
) -> None:
    first_token = _login(ticketing_harness.client, "tourist_demo")["access_token"]

    async def create_pagination_owner() -> None:
        async with ticketing_harness.session_factory() as session:
            tourist_role = await session.scalar(select(Role).where(Role.name == "tourist"))
            assert tourist_role is not None
            owner = User(
                username="pagination_tourist",
                display_name="Pagination Tourist",
                password_hash=hash_password(DEMO_PASSWORD),
                is_active=True,
            )
            session.add(owner)
            await session.flush()
            session.add(UserRole(user_id=owner.id, role_id=tourist_role.id))
            await session.commit()

    asyncio.run(create_pagination_owner())
    second_token = _login(ticketing_harness.client, "pagination_tourist")["access_token"]

    async def create_slot() -> UUID:
        async with ticketing_harness.session_factory() as session:
            ticket_type = await session.scalar(select(TicketType).where(TicketType.code == "adult"))
            assert ticket_type is not None
            slot = TicketSlot(
                ticket_type_id=ticket_type.id,
                visit_date=datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=45),
                start_time=time(13, 0),
                end_time=time(14, 0),
                is_active=True,
            )
            slot.inventory = TicketInventory(capacity=10, reserved=0, sold=0)
            session.add(slot)
            await session.commit()
            return slot.id

    slot_id = asyncio.run(create_slot())
    first = _create_order(
        ticketing_harness,
        token=first_token,
        slot_id=slot_id,
        quantity=1,
        key="pagination-owner-one-001",
    )
    second = _create_order(
        ticketing_harness,
        token=second_token,
        slot_id=slot_id,
        quantity=1,
        key="pagination-owner-two-001",
    )
    assert first.status_code == 201
    assert second.status_code == 201

    second_page = ticketing_harness.client.get(
        "/api/v1/ticketing/orders?page=1&page_size=1",
        headers=_bearer(second_token),
    )
    assert second_page.status_code == 200
    body = second_page.json()
    assert body["items"] == [second.json()]
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert body["total"] == 1

    too_large = ticketing_harness.client.get(
        "/api/v1/ticketing/orders?page_size=101",
        headers=_bearer(first_token),
    )
    assert too_large.status_code == 422


def test_expired_reservation_releases_inventory_and_cannot_be_paid(
    ticketing_harness: TicketingHarness,
) -> None:
    token = _login(ticketing_harness.client, "tourist_demo")["access_token"]
    created = _create_order(
        ticketing_harness,
        token=token,
        slot_id=ticketing_harness.gate_slot_id,
        quantity=1,
        key="expiry-create-001",
    )
    order_id = UUID(created.json()["id"])

    async def force_expiry() -> None:
        async with ticketing_harness.session_factory() as session:
            await session.execute(
                update(TicketOrder)
                .where(TicketOrder.id == order_id)
                .values(expires_at=datetime.now(ZoneInfo("UTC")) - timedelta(minutes=1))
            )
            await session.commit()

    asyncio.run(force_expiry())
    detail = ticketing_harness.client.get(
        f"/api/v1/ticketing/orders/{order_id}",
        headers=_bearer(token),
    )
    payment = _pay_order(
        ticketing_harness,
        token=token,
        order_id=str(order_id),
        key="expiry-payment-001",
    )

    assert detail.status_code == 200
    assert detail.json()["status"] == "EXPIRED"
    assert payment.status_code == 409


def test_ticketing_seed_has_no_duplicate_catalog_rows(
    ticketing_harness: TicketingHarness,
) -> None:
    assert (
        asyncio.run(
            seed_database(
                ticketing_harness.session_factory,
                include_demo_accounts=True,
            )
        )
        is False
    )

    async def counts() -> tuple[int, int, int]:
        async with ticketing_harness.session_factory() as session:
            return (
                int(await session.scalar(select(func.count()).select_from(TicketType)) or 0),
                int(await session.scalar(select(func.count()).select_from(TicketSlot)) or 0),
                int(await session.scalar(select(func.count()).select_from(TicketOrder)) or 0),
            )

    ticket_types, slots, orders = asyncio.run(counts())
    assert ticket_types == 4
    assert slots >= 85
    assert orders >= 1


def test_face_demo_checks_consent_ownership_and_ticket_without_consuming_it(
    ticketing_harness: TicketingHarness,
) -> None:
    owner_token = _login(ticketing_harness.client, "tourist_demo")["access_token"]
    other_token = _login(ticketing_harness.client, "tourist_two")["access_token"]
    created = _create_order(
        ticketing_harness,
        token=owner_token,
        slot_id=ticketing_harness.gate_slot_id,
        quantity=1,
        key="face-demo-create-001",
    )
    paid = _pay_order(
        ticketing_harness,
        token=owner_token,
        order_id=created.json()["id"],
        key="face-demo-payment-001",
    )
    assert paid.status_code == 200
    ticket_id = paid.json()["tickets"][0]["id"]
    endpoint = f"/api/v1/ticketing/tickets/{ticket_id}/face-demo/verify"

    owner_match = ticketing_harness.client.post(
        endpoint,
        headers=_bearer(owner_token),
        json={"sample": "OWNER", "consent": True},
    )
    other_sample = ticketing_harness.client.post(
        endpoint,
        headers=_bearer(owner_token),
        json={"sample": "OTHER", "consent": True},
    )
    missing_consent = ticketing_harness.client.post(
        endpoint,
        headers=_bearer(owner_token),
        json={"sample": "OWNER", "consent": False},
    )
    wrong_owner = ticketing_harness.client.post(
        endpoint,
        headers=_bearer(other_token),
        json={"sample": "OWNER", "consent": True},
    )

    assert owner_match.status_code == 200
    assert owner_match.headers["Cache-Control"] == "no-store"
    assert owner_match.json() == {
        "ticket_id": ticket_id,
        "ticket_code": paid.json()["tickets"][0]["ticket_code"],
        "result": "DEMO_MATCHED",
        "provider": "demo_face_gate",
        "is_demo": True,
        "biometric_processed": False,
        "admission_granted": False,
        "disclaimer": (
            "仅为无生物信息的人脸接入演示; 未调用摄像头或活体检测, "
            "不会放行或核销门票。"
        ),
    }
    assert other_sample.status_code == 200
    assert other_sample.json()["result"] == "DEMO_NOT_MATCHED"
    assert missing_consent.status_code == 422
    assert wrong_owner.status_code == 404

    # 两次演示匹配都是只读操作, 电子票必须保持 ISSUED 才能继续展示 QR 或办理退票。
    refreshed = ticketing_harness.client.get(
        f"/api/v1/ticketing/orders/{created.json()['id']}",
        headers=_bearer(owner_token),
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["tickets"][0]["status"] == TICKET_ISSUED

    async def void_ticket() -> None:
        async with ticketing_harness.session_factory() as session:
            await session.execute(
                update(ElectronicTicket)
                .where(ElectronicTicket.id == UUID(ticket_id))
                .values(status="VOID")
            )
            await session.commit()

    asyncio.run(void_ticket())
    ineligible = ticketing_harness.client.post(
        endpoint,
        headers=_bearer(owner_token),
        json={"sample": "OWNER", "consent": True},
    )
    assert ineligible.status_code == 409
    assert ineligible.json()["error"]["code"] == "FACE_DEMO_TICKET_NOT_ELIGIBLE"

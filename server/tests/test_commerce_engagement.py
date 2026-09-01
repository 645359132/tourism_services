"""Checkpoint 7 commerce, engagement, support, groups, and facilities tests."""

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
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.base import Base
from app.db.models.commerce import (
    PointAccount,
    PointLedgerEntry,
    Product,
    ProductInventory,
    Reward,
    ShopOrder,
    ShopOrderItem,
)
from app.db.models.engagement import (
    GroupMember,
    SupportMessage,
    TravelGroup,
)
from app.db.models.role import Role, UserRole
from app.db.models.user import User
from app.db.session import get_session
from app.main import create_app
from app.schemas.commerce import DeliveryRequest
from app.scripts.seed import DEMO_PASSWORD, seed_database
from app.services.auth import get_user_by_id
from app.services.commerce import checkout_cart
from app.services.support import post_message


@dataclass(slots=True)
class Checkpoint7Harness:
    client: TestClient
    application: FastAPI
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings


@pytest.fixture(scope="module")
def cp7_harness(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Checkpoint7Harness]:
    database_path: Path = tmp_path_factory.mktemp("cp7") / "cp7.db"
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
            for username in (
                "cp7_tourist_two",
                "cp7_checkout_one",
                "cp7_checkout_two",
                "cp7_group_late",
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
            await session.commit()

    asyncio.run(prepare())
    asyncio.run(engine.dispose())
    settings = Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="checkpoint7-test-jwt-secret-4f1f9887a310",
        enable_demo_accounts=True,
        crowd_publish_interval_seconds=3600,
        queue_publish_interval_seconds=3600,
        shop_order_reservation_minutes=15,
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
        yield Checkpoint7Harness(client, application, session_factory, settings)
    asyncio.run(engine.dispose())


def _login(harness: Checkpoint7Harness, username: str) -> str:
    response = harness.client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.json()
    return response.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _delivery() -> dict[str, str]:
    return {
        "name": "演示游客",
        "phone": "13800000000",
        "province": "浙江省",
        "city": "杭州市",
        "address_line": "智慧景区游客中心 1 号",
        "postal_code": "310000",
    }


def test_server_authoritative_cart_checkout_payment_and_point_source_uniqueness(
    cp7_harness: Checkpoint7Harness,
) -> None:
    categories = cp7_harness.client.get("/api/v1/shop/categories")
    assert categories.status_code == 200
    assert set(categories.json()["items"][0]) == {
        "id",
        "code",
        "name",
        "description",
        "sort_order",
    }
    products = cp7_harness.client.get("/api/v1/shop/products")
    assert products.status_code == 200
    product = products.json()["items"][0]
    assert set(product) == {
        "id",
        "category_id",
        "sku",
        "name",
        "description",
        "price_cents",
        "effective_price_cents",
        "stock",
        "points_price",
        "tags",
        "campaign_id",
        "campaign_name",
        "provider",
        "is_demo",
    }
    token = _login(cp7_harness, "tourist_demo")
    forged = cp7_harness.client.post(
        "/api/v1/shop/cart/items",
        headers=_bearer(token),
        json={
            "product_id": product["id"],
            "quantity": 1,
            "unit_price_cents": 1,
        },
    )
    assert forged.status_code == 422
    added = cp7_harness.client.post(
        "/api/v1/shop/cart/items",
        headers=_bearer(token),
        json={"product_id": product["id"], "quantity": 1},
    )
    assert added.status_code == 200, added.json()
    assert set(added.json()) == {
        "id",
        "items",
        "total_quantity",
        "subtotal_cents",
        "discount_cents",
        "total_cents",
        "updated_at",
    }

    async def raise_price() -> int:
        async with cp7_harness.session_factory() as session:
            model = await session.get(Product, UUID(product["id"]))
            assert model is not None
            model.price_cents += 1_111
            await session.commit()
            return model.price_cents

    authoritative = asyncio.run(raise_price())
    checkout = cp7_harness.client.post(
        "/api/v1/shop/cart/checkout",
        headers=_bearer(token),
        json={
            "delivery": _delivery(),
            "idempotency_key": "shop-checkout-authority-0001",
        },
    )
    assert checkout.status_code == 201, checkout.json()
    order = checkout.json()
    assert order["items"][0]["unit_price_cents"] == authoritative
    assert order["subtotal_cents"] == authoritative
    paid = cp7_harness.client.post(
        f"/api/v1/shop/orders/{order['id']}/pay",
        headers=_bearer(token),
        json={"idempotency_key": "shop-pay-authority-0001"},
    )
    assert paid.status_code == 200, paid.json()
    assert paid.json()["status"] == "PAID"
    replay = cp7_harness.client.post(
        f"/api/v1/shop/orders/{order['id']}/pay",
        headers=_bearer(token),
        json={"idempotency_key": "shop-pay-authority-0001"},
    )
    assert replay.status_code == 200

    async def point_source_count() -> tuple[int, int]:
        async with cp7_harness.session_factory() as session:
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.source_type == "SHOP_ORDER",
                        PointLedgerEntry.source_id == UUID(order["id"]),
                    )
                )
                or 0
            )
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            assert user_id is not None
            account = await session.get(PointAccount, user_id)
            assert account is not None
            return count, account.balance

    ledger_count, balance = asyncio.run(point_source_count())
    assert ledger_count == 1
    assert balance >= 500


def test_concurrent_checkout_last_stock_has_one_winner(
    cp7_harness: Checkpoint7Harness,
) -> None:
    product = cp7_harness.client.get("/api/v1/shop/products").json()["items"][1]
    tokens = {
        username: _login(cp7_harness, username)
        for username in ("cp7_checkout_one", "cp7_checkout_two")
    }
    for token in tokens.values():
        response = cp7_harness.client.post(
            "/api/v1/shop/cart/items",
            headers=_bearer(token),
            json={"product_id": product["id"], "quantity": 1},
        )
        assert response.status_code == 200

    async def set_last_stock() -> None:
        async with cp7_harness.session_factory() as session:
            await session.execute(
                update(ProductInventory)
                .where(ProductInventory.product_id == UUID(product["id"]))
                .values(stock=1)
            )
            await session.commit()

    asyncio.run(set_last_stock())

    async def race() -> list[str]:
        gate = asyncio.Event()

        async def attempt(username: str, key: str) -> str:
            async with cp7_harness.session_factory() as session:
                user_id = await session.scalar(select(User.id).where(User.username == username))
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                try:
                    await checkout_cart(
                        session,
                        user=user,
                        delivery=DeliveryRequest(**_delivery()),
                        idempotency_key=key,
                        settings=cp7_harness.settings,
                    )
                    return "ORDER"
                except AppError as exc:
                    return exc.code

        tasks = [
            asyncio.create_task(attempt("cp7_checkout_one", "checkout-race-one")),
            asyncio.create_task(attempt("cp7_checkout_two", "checkout-race-two")),
        ]
        gate.set()
        return list(await asyncio.gather(*tasks))

    outcomes = asyncio.run(race())
    assert outcomes.count("ORDER") == 1
    assert outcomes.count("INSUFFICIENT_STOCK") == 1

    async def stock_and_orders() -> tuple[int, int]:
        async with cp7_harness.session_factory() as session:
            inventory = await session.get(ProductInventory, UUID(product["id"]))
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ShopOrder)
                    .where(
                        ShopOrder.idempotency_key.in_(("checkout-race-one", "checkout-race-two"))
                    )
                )
                or 0
            )
            assert inventory is not None
            return inventory.stock, count

    assert asyncio.run(stock_and_orders()) == (0, 1)


def test_expired_shop_hold_restores_stock_once(
    cp7_harness: Checkpoint7Harness,
) -> None:
    async def expire_winner() -> tuple[UUID, UUID, str, str]:
        async with cp7_harness.session_factory() as session:
            order = await session.scalar(
                select(ShopOrder).where(
                    ShopOrder.idempotency_key.in_(("checkout-race-one", "checkout-race-two"))
                )
            )
            assert order is not None
            username = await session.scalar(select(User.username).where(User.id == order.user_id))
            assert username is not None
            loser_username = next(
                candidate
                for candidate in ("cp7_checkout_one", "cp7_checkout_two")
                if candidate != username
            )
            product_id = await session.scalar(
                select(ShopOrderItem.product_id).where(ShopOrderItem.order_id == order.id)
            )
            assert product_id is not None
            order.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
            return order.id, product_id, username, loser_username

    order_id, product_id, username, loser_username = asyncio.run(expire_winner())
    catalog = cp7_harness.client.get("/api/v1/shop/products")
    assert catalog.status_code == 200
    restored_product = next(
        item for item in catalog.json()["items"] if item["id"] == str(product_id)
    )
    assert restored_product["stock"] == 1
    loser_token = _login(cp7_harness, loser_username)
    loser_cart = cp7_harness.client.get(
        "/api/v1/shop/cart",
        headers=_bearer(loser_token),
    ).json()
    loser_item = next(item for item in loser_cart["items"] if item["product_id"] == str(product_id))
    cart_update = cp7_harness.client.put(
        f"/api/v1/shop/cart/items/{loser_item['id']}",
        headers=_bearer(loser_token),
        json={"quantity": 1},
    )
    assert cart_update.status_code == 200
    token = _login(cp7_harness, username)
    first = cp7_harness.client.get(
        f"/api/v1/shop/orders/{order_id}",
        headers=_bearer(token),
    )
    second = cp7_harness.client.get(
        f"/api/v1/shop/orders/{order_id}",
        headers=_bearer(token),
    )
    assert first.status_code == 200
    assert first.json()["status"] == "EXPIRED"
    assert second.json()["status"] == "EXPIRED"

    async def stock() -> int:
        async with cp7_harness.session_factory() as session:
            inventory = await session.get(ProductInventory, product_id)
            assert inventory is not None
            return inventory.stock

    assert asyncio.run(stock()) == 1


def test_points_redemption_rollback_and_share_award_once(
    cp7_harness: Checkpoint7Harness,
) -> None:
    token = _login(cp7_harness, "tourist_demo")
    before = cp7_harness.client.get(
        "/api/v1/points/account",
        headers=_bearer(token),
    ).json()
    product_id = cp7_harness.client.get("/api/v1/shop/products").json()["items"][0]["id"]
    invalid_share = cp7_harness.client.post(
        "/api/v1/shares",
        headers=_bearer(token),
        json={
            "content_type": "PRODUCT",
            "ref_id": str(UUID(int=0)),
            "platform": "demo_moments",
            "caption": "不存在商品",
            "idempotency_key": "share-invalid-target-0001",
        },
    )
    assert invalid_share.status_code == 404
    share_payload = {
        "content_type": "PRODUCT",
        "ref_id": product_id,
        "platform": "demo_moments",
        "caption": "文化路线分享",
        "idempotency_key": "share-award-first-0001",
    }
    first_share = cp7_harness.client.post(
        "/api/v1/shares",
        headers=_bearer(token),
        json=share_payload,
    )
    assert first_share.status_code == 200, first_share.json()
    duplicate_share = cp7_harness.client.post(
        "/api/v1/shares",
        headers=_bearer(token),
        json={
            **share_payload,
            "idempotency_key": "share-award-second-0001",
        },
    )
    assert duplicate_share.status_code == 200
    assert duplicate_share.json()["id"] == first_share.json()["id"]
    cross_platform_duplicate = cp7_harness.client.post(
        "/api/v1/shares",
        headers=_bearer(token),
        json={
            **share_payload,
            "platform": "demo_group",
            "idempotency_key": "share-award-cross-platform-0001",
        },
    )
    assert cross_platform_duplicate.status_code == 200
    assert cross_platform_duplicate.json()["id"] == first_share.json()["id"]
    after_share = cp7_harness.client.get(
        "/api/v1/points/account",
        headers=_bearer(token),
    ).json()
    assert after_share["balance"] - before["balance"] == 25

    rewards = cp7_harness.client.get("/api/v1/points/rewards").json()["items"]
    sold_out_reward = rewards[0]
    insufficient_reward = rewards[1]

    async def prepare_failures() -> tuple[int, int]:
        async with cp7_harness.session_factory() as session:
            first = await session.get(Reward, UUID(sold_out_reward["id"]))
            second = await session.get(Reward, UUID(insufficient_reward["id"]))
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            assert first is not None
            assert second is not None
            assert user_id is not None
            account = await session.get(PointAccount, user_id)
            assert account is not None
            first.stock = 0
            second.stock = 1
            balance = account.balance
            await session.commit()
            return balance, second.stock

    balance_before, second_stock = asyncio.run(prepare_failures())
    sold_out = cp7_harness.client.post(
        "/api/v1/points/redeem",
        headers=_bearer(token),
        json={
            "reward_id": sold_out_reward["id"],
            "idempotency_key": "redeem-sold-out-0001",
        },
    )
    assert sold_out.status_code == 409
    assert sold_out.json()["error"]["code"] == "REWARD_SOLD_OUT"

    async def force_insufficient_points() -> None:
        async with cp7_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            assert user_id is not None
            account = await session.get(PointAccount, user_id)
            assert account is not None
            account.balance = 0
            await session.commit()

    asyncio.run(force_insufficient_points())
    insufficient = cp7_harness.client.post(
        "/api/v1/points/redeem",
        headers=_bearer(token),
        json={
            "reward_id": insufficient_reward["id"],
            "idempotency_key": "redeem-insufficient-0001",
        },
    )
    assert insufficient.status_code == 409
    assert insufficient.json()["error"]["code"] == "INSUFFICIENT_POINTS"

    async def rollback_state() -> tuple[int, int, int]:
        async with cp7_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            reward = await session.get(Reward, UUID(insufficient_reward["id"]))
            assert user_id is not None
            assert reward is not None
            account = await session.get(PointAccount, user_id)
            spend_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.user_id == user_id,
                        PointLedgerEntry.entry_type == "SPEND",
                    )
                )
                or 0
            )
            assert account is not None
            return account.balance, reward.stock, spend_count

    balance_after, stock_after, spend_count = asyncio.run(rollback_state())
    assert balance_after == 0
    assert stock_after == second_stock
    assert spend_count == 0
    assert balance_before >= 0

    async def fund_for_success() -> int:
        async with cp7_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            reward = await session.get(Reward, UUID(insufficient_reward["id"]))
            assert user_id is not None
            assert reward is not None
            account = await session.get(PointAccount, user_id)
            assert account is not None
            account.balance = reward.points_cost * 2
            reward.stock = 1
            await session.commit()
            return reward.points_cost

    reward_cost = asyncio.run(fund_for_success())
    redeemed = cp7_harness.client.post(
        "/api/v1/points/redeem",
        headers=_bearer(token),
        json={
            "reward_id": insufficient_reward["id"],
            "idempotency_key": "redeem-success-0001",
        },
    )
    assert redeemed.status_code == 200, redeemed.json()
    assert redeemed.json()["points_spent"] == reward_cost
    redeemed_replay = cp7_harness.client.post(
        "/api/v1/points/redeem",
        headers=_bearer(token),
        json={
            "reward_id": insufficient_reward["id"],
            "idempotency_key": "redeem-success-0001",
        },
    )
    assert redeemed_replay.status_code == 200
    assert redeemed_replay.json()["id"] == redeemed.json()["id"]

    async def successful_redemption_state() -> tuple[int, int, int]:
        async with cp7_harness.session_factory() as session:
            user_id = await session.scalar(select(User.id).where(User.username == "tourist_demo"))
            assert user_id is not None
            account = await session.get(PointAccount, user_id)
            reward = await session.get(Reward, UUID(insufficient_reward["id"]))
            ledger_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PointLedgerEntry)
                    .where(
                        PointLedgerEntry.user_id == user_id,
                        PointLedgerEntry.source_type == "REDEMPTION",
                        PointLedgerEntry.source_id == UUID(redeemed.json()["id"]),
                    )
                )
                or 0
            )
            assert account is not None
            assert reward is not None
            return account.balance, reward.stock, ledger_count

    assert asyncio.run(successful_redemption_state()) == (reward_cost, 0, 1)


def test_feedback_rbac_state_machine_faq_and_accessible_facilities(
    cp7_harness: Checkpoint7Harness,
) -> None:
    tourist = _login(cp7_harness, "tourist_demo")
    other = _login(cp7_harness, "cp7_tourist_two")
    support = _login(cp7_harness, "support_demo")
    merchant = _login(cp7_harness, "merchant_demo")
    created = cp7_harness.client.post(
        "/api/v1/feedback",
        headers=_bearer(tourist),
        json={
            "kind": "COMPLAINT",
            "title": "排队提示不清晰",
            "content": "希望展示预计叫号时间",
            "priority": "HIGH",
        },
    )
    assert created.status_code == 201, created.json()
    feedback = created.json()
    assert set(feedback) == {
        "id",
        "ticket_no",
        "kind",
        "title",
        "content",
        "status",
        "priority",
        "latest_response",
        "rating",
        "follow_ups",
        "created_at",
        "updated_at",
    }
    hidden = cp7_harness.client.get(
        f"/api/v1/feedback/{feedback['id']}",
        headers=_bearer(other),
    )
    assert hidden.status_code == 404
    forbidden = cp7_harness.client.get(
        "/api/v1/feedback",
        headers=_bearer(merchant),
    )
    assert forbidden.status_code == 403
    tourist_assign = cp7_harness.client.post(
        f"/api/v1/feedback/{feedback['id']}/assign",
        headers=_bearer(tourist),
        json={},
    )
    assert tourist_assign.status_code == 403
    assigned = cp7_harness.client.post(
        f"/api/v1/feedback/{feedback['id']}/assign",
        headers=_bearer(support),
        json={"note": "客服已接单"},
    )
    assert assigned.status_code == 200, assigned.json()
    assert assigned.json()["status"] == "IN_PROGRESS"
    resolved = cp7_harness.client.post(
        f"/api/v1/feedback/{feedback['id']}/resolve",
        headers=_bearer(support),
        json={"resolution": "已增加演示叫号说明"},
    )
    assert resolved.status_code == 200, resolved.json()
    assert resolved.json()["status"] == "RESOLVED"
    follow_up = cp7_harness.client.post(
        f"/api/v1/feedback/{feedback['id']}/rating",
        headers=_bearer(tourist),
        json={"rating": 5, "comment": "处理清晰"},
    )
    assert follow_up.status_code == 200, follow_up.json()
    assert follow_up.json()["status"] == "CLOSED"
    assert follow_up.json()["follow_ups"][0]["author_name"] == "游客"

    faqs = cp7_harness.client.get("/api/v1/faqs")
    assert faqs.status_code == 200
    assert len(faqs.json()["items"]) == 4
    assert "sort_order" in faqs.json()["items"][0]
    facilities = cp7_harness.client.get(
        "/api/v1/guide/facilities",
        params={"accessible_only": True},
    )
    assert facilities.status_code == 200
    assert len(facilities.json()["items"]) == 4
    assert all(item["wheelchair_ok"] for item in facilities.json()["items"])


def test_persisted_support_ws_ticket_scope_and_monotonic_messages(
    cp7_harness: Checkpoint7Harness,
) -> None:
    tourist = _login(cp7_harness, "tourist_demo")
    other = _login(cp7_harness, "cp7_tourist_two")
    created = cp7_harness.client.post(
        "/api/v1/support/conversations",
        headers=_bearer(tourist),
        json={"subject": "演示客服咨询"},
    )
    assert created.status_code == 201, created.json()
    conversation_id = created.json()["id"]
    denied = cp7_harness.client.post(
        "/api/v1/support/ws-tickets",
        headers=_bearer(other),
        json={"conversation_id": conversation_id},
    )
    assert denied.status_code == 404

    posted = cp7_harness.client.post(
        f"/api/v1/support/conversations/{conversation_id}/messages",
        headers=_bearer(tourist),
        json={
            "content": "我想咨询退票",
            "idempotency_key": "support-rest-message-0001",
        },
    )
    assert posted.status_code == 201, posted.json()
    assert [item["sequence"] for item in posted.json()["items"]] == [1, 2]
    assert [item["provider"] for item in posted.json()["items"]] == [
        "human",
        "demo_support_bot",
    ]
    replay = cp7_harness.client.post(
        f"/api/v1/support/conversations/{conversation_id}/messages",
        headers=_bearer(tourist),
        json={
            "content": "我想咨询退票",
            "idempotency_key": "support-rest-message-0001",
        },
    )
    assert replay.status_code == 201
    assert [item["sequence"] for item in replay.json()["items"]] == [1, 2]

    ticket = cp7_harness.client.post(
        "/api/v1/support/ws-tickets",
        headers=_bearer(tourist),
        json={"conversation_id": conversation_id},
    ).json()["ticket"]
    wrong_scope = f"/api/v1/ws/queues/{conversation_id}?ticket={ticket}"
    with pytest.raises(WebSocketDisconnect) as wrong_closed:
        with cp7_harness.client.websocket_connect(wrong_scope) as socket:
            socket.receive_json()
    assert wrong_closed.value.code == 4401
    support_path = f"/api/v1/ws/support/{conversation_id}?ticket={ticket}"
    with cp7_harness.client.websocket_connect(support_path) as websocket:
        initial = websocket.receive_json()
        assert initial["type"] == "support.updated"
        websocket.send_json(
            {
                "type": "message.send",
                "data": {
                    "content": "还需要多久?",
                    "idempotency_key": "support-ws-message-0001",
                },
            }
        )
        messages = [websocket.receive_json(), websocket.receive_json()]
        assert [item["data"]["message"]["sequence"] for item in messages] == [3, 4]
        assert [item["data"]["source"] for item in messages] == [
            "human",
            "demo_support_bot",
        ]
    assert cp7_harness.application.state.support_hub.connection_count == 0
    with pytest.raises(WebSocketDisconnect) as replay_closed:
        with cp7_harness.client.websocket_connect(support_path) as socket:
            socket.receive_json()
    assert replay_closed.value.code == 4401
    history = cp7_harness.client.get(
        f"/api/v1/support/conversations/{conversation_id}/messages",
        headers=_bearer(tourist),
    )
    assert [item["sequence"] for item in history.json()["items"]] == [1, 2, 3, 4]

    malformed_ticket = cp7_harness.client.post(
        "/api/v1/support/ws-tickets",
        headers=_bearer(tourist),
        json={"conversation_id": conversation_id},
    ).json()["ticket"]
    with cp7_harness.client.websocket_connect(
        f"/api/v1/ws/support/{conversation_id}?ticket={malformed_ticket}"
    ) as websocket:
        websocket.receive_json()
        websocket.send_json(["not", "an", "object"])
        with pytest.raises(WebSocketDisconnect) as malformed_closed:
            websocket.receive_json()
        assert malformed_closed.value.code == 1008

    async def concurrent_same_key() -> tuple[list[int], int]:
        gate = asyncio.Event()

        async def attempt() -> list[int]:
            async with cp7_harness.session_factory() as session:
                user_id = await session.scalar(
                    select(User.id).where(User.username == "tourist_demo")
                )
                assert user_id is not None
                user = await get_user_by_id(session, user_id)
                assert user is not None
                await gate.wait()
                _, persisted = await post_message(
                    session,
                    conversation_id=UUID(conversation_id),
                    user=user,
                    content="并发同一条消息",
                    idempotency_key="support-concurrent-same-key",
                )
                return [item.sequence for item in persisted]

        tasks = [asyncio.create_task(attempt()), asyncio.create_task(attempt())]
        gate.set()
        results = await asyncio.gather(*tasks)
        async with cp7_harness.session_factory() as session:
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(SupportMessage)
                    .where(
                        SupportMessage.conversation_id == UUID(conversation_id),
                        SupportMessage.sequence.in_((5, 6)),
                    )
                )
                or 0
            )
        return sorted({value for result in results for value in result}), count

    sequences, count = asyncio.run(concurrent_same_key())
    assert sequences == [5, 6]
    assert count == 2


def test_group_invite_dual_privacy_meeting_and_lost_alert(
    cp7_harness: Checkpoint7Harness,
) -> None:
    owner = _login(cp7_harness, "tourist_demo")
    member = _login(cp7_harness, "cp7_tourist_two")
    late = _login(cp7_harness, "cp7_group_late")
    created = cp7_harness.client.post(
        "/api/v1/groups/create",
        headers=_bearer(owner),
        json={"name": "同行演示组", "invite_valid_minutes": 60},
    )
    assert created.status_code == 201, created.json()
    group = created.json()
    assert set(group) == {
        "id",
        "name",
        "invite_code",
        "revision",
        "itinerary_id",
        "itinerary_revision",
        "share_itinerary",
        "share_location",
        "share_member_status",
        "members",
        "meeting_point",
        "provider",
        "is_demo",
        "updated_at",
    }
    enabled = cp7_harness.client.put(
        f"/api/v1/groups/{group['id']}/privacy",
        headers=_bearer(owner),
        json={
            "share_itinerary": True,
            "share_location": True,
            "share_member_status": True,
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["members"][0]["share_location"] is False
    joined = cp7_harness.client.post(
        "/api/v1/groups/join",
        headers=_bearer(member),
        json={"invite_code": group["invite_code"]},
    )
    assert joined.status_code == 200, joined.json()
    joined_member = next(
        item for item in joined.json()["members"] if item["display_name"] == "cp7_tourist_two"
    )
    assert joined_member["share_location"] is False
    assert joined_member["share_status"] is False
    assert joined_member["status"] == "HIDDEN"

    private_status = cp7_harness.client.post(
        f"/api/v1/groups/{group['id']}/member-status",
        headers=_bearer(member),
        json={
            "status": "MOVING",
            "note": "前往集合点",
            "share_location": False,
            "share_status": True,
            "latitude": 30.25,
            "longitude": 120.15,
        },
    )
    assert private_status.status_code == 200, private_status.json()
    private_member = next(
        item
        for item in private_status.json()["members"]
        if item["display_name"] == "cp7_tourist_two"
    )
    assert private_member["latitude"] is None
    assert private_member["longitude"] is None

    shared_status = cp7_harness.client.post(
        f"/api/v1/groups/{group['id']}/member-status",
        headers=_bearer(member),
        json={
            "status": "WAITING",
            "note": "已到达",
            "share_location": True,
            "share_status": True,
            "latitude": 30.25,
            "longitude": 120.15,
        },
    )
    assert shared_status.status_code == 200, shared_status.json()
    shared_member = next(
        item
        for item in shared_status.json()["members"]
        if item["display_name"] == "cp7_tourist_two"
    )
    assert shared_member["latitude"] == 30.25
    assert shared_member["longitude"] == 120.15

    hidden = cp7_harness.client.put(
        f"/api/v1/groups/{group['id']}/privacy",
        headers=_bearer(owner),
        json={
            "share_itinerary": False,
            "share_location": False,
            "share_member_status": False,
        },
    )
    assert hidden.status_code == 200, hidden.json()
    hidden_member = next(
        item for item in hidden.json()["members"] if item["display_name"] == "cp7_tourist_two"
    )
    assert hidden_member["status"] == "HIDDEN"
    assert hidden_member["note"] == ""
    assert hidden_member["latitude"] is None
    assert hidden_member["longitude"] is None

    facilities = cp7_harness.client.get("/api/v1/guide/facilities").json()["items"]
    node_id = next(item["node_id"] for item in facilities if item["node_id"])
    meeting = cp7_harness.client.post(
        f"/api/v1/groups/{group['id']}/meeting-points",
        headers=_bearer(member),
        json={
            "name": "游客中心集合",
            "note": "入口内侧等候",
            "node_id": node_id,
        },
    )
    assert meeting.status_code == 201, meeting.json()
    assert meeting.json()["meeting_point"]["note"] == "入口内侧等候"
    lost = cp7_harness.client.post(
        f"/api/v1/groups/{group['id']}/lost-alerts",
        headers=_bearer(member),
        json={
            "message": "我与队伍走散了",
            "last_seen_node_id": node_id,
        },
    )
    assert lost.status_code == 201, lost.json()
    assert lost.json()["last_seen_node_id"] == node_id

    async def expire_invite() -> None:
        async with cp7_harness.session_factory() as session:
            await session.execute(
                update(TravelGroup)
                .where(TravelGroup.id == UUID(group["id"]))
                .values(invite_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()

    asyncio.run(expire_invite())
    expired = cp7_harness.client.post(
        "/api/v1/groups/join",
        headers=_bearer(late),
        json={"invite_code": group["invite_code"]},
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "INVITE_EXPIRED"

    async def member_opt_in_survived_owner_toggle() -> bool:
        async with cp7_harness.session_factory() as session:
            user_id = await session.scalar(
                select(User.id).where(User.username == "cp7_tourist_two")
            )
            assert user_id is not None
            model = await session.scalar(
                select(GroupMember).where(
                    GroupMember.group_id == UUID(group["id"]),
                    GroupMember.user_id == user_id,
                )
            )
            assert model is not None
            return model.share_location

    assert asyncio.run(member_opt_in_survived_owner_toggle()) is True

"""Checkpoint 9 Locust workload using isolated, pre-seeded tourist accounts.

Run from ``server/`` after ``tourism-load-seed``.  Every Locust user claims one
identity; exhausting the configured pool is reported as a setup failure rather
than sharing mutable carts, orders, or reservation schedules.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import date, timedelta
from time import perf_counter
from typing import Any
from uuid import uuid4

import websocket
from locust import HttpUser, between, events, task
from locust.exception import StopUser

from load.common import (
    ScenarioDataMissing,
    UniqueUserAllocator,
    UserPoolExhausted,
    env_int,
    require_scenario_item,
    websocket_url,
)

LOAD_USER_COUNT = env_int("TOURISM_LOAD_USER_COUNT", 100, minimum=1)
LOAD_USER_OFFSET = env_int("TOURISM_LOAD_USER_OFFSET", 0)
LOAD_USER_PREFIX = os.getenv("TOURISM_LOAD_USER_PREFIX", "load_tourist_")
LOAD_USER_PASSWORD = os.getenv("TOURISM_LOAD_USER_PASSWORD")
if not LOAD_USER_PASSWORD:
    raise RuntimeError("TOURISM_LOAD_USER_PASSWORD must be set for the Locust workload")
WS_TIMEOUT_SECONDS = env_int("TOURISM_LOAD_WS_TIMEOUT_SECONDS", 5, minimum=1, maximum=30)

IDENTITIES = UniqueUserAllocator(
    prefix=LOAD_USER_PREFIX,
    count=LOAD_USER_COUNT,
    offset=LOAD_USER_OFFSET,
)


@events.test_start.add_listener
def _reset_identity_pool(**_: object) -> None:
    IDENTITIES.reset()


class TourismUser(HttpUser):
    """A tourist journey with one bounded write of each inventory workflow."""

    wait_time = between(0.2, 0.8)

    def on_start(self) -> None:
        try:
            self.identity = IDENTITIES.claim()
        except UserPoolExhausted as exc:
            self.environment.events.request.fire(
                request_type="SETUP",
                name="unique load identity",
                response_time=0,
                response_length=0,
                exception=exc,
            )
            raise StopUser from exc

        self.run_id = uuid4().hex
        self.sequence = 0
        self.access_token = ""
        self.ticket_done = False
        self.reservation_done = False
        self.shop_done = False
        self._login()
        if not self.access_token:
            raise StopUser

        # Guarantee that even a short baseline exercises the three bounded
        # inventory mutations once for every unique user.
        self.ticket_purchase()
        self.experience_reservation()
        self.shop_checkout()

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _key(self, operation: str) -> str:
        self.sequence += 1
        return f"load-{operation}-{self.identity.index}-{self.run_id[:12]}-{self.sequence}"

    @staticmethod
    def _json(response: Any, *, required_key: str | None = None) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            response.failure("response was not valid JSON")
            return None
        if not isinstance(payload, dict):
            response.failure("response JSON was not an object")
            return None
        if required_key is not None and required_key not in payload:
            response.failure(f"response JSON omitted {required_key!r}")
            return None
        response.success()
        return payload

    def _login(self) -> None:
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": self.identity.username, "password": LOAD_USER_PASSWORD},
            name="POST /api/v1/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login returned HTTP {response.status_code}")
                return
            payload = self._json(response, required_key="access_token")
            if payload is not None:
                self.access_token = str(payload["access_token"])

    def _items(
        self,
        path: str,
        *,
        name: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        with self.client.get(
            path,
            params=params,
            headers=headers,
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"list returned HTTP {response.status_code}")
                return []
            payload = self._json(response, required_key="items")
            if payload is None or not isinstance(payload["items"], list):
                if payload is not None:
                    response.failure("response 'items' was not a list")
                return []
            return [item for item in payload["items"] if isinstance(item, dict)]

    def _required_item(
        self,
        items: list[dict[str, Any]],
        *,
        scenario: str,
        reason: str,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        try:
            return require_scenario_item(
                self.environment.events.request,
                items,
                scenario=scenario,
                reason=reason,
                predicate=predicate,
            )
        except ScenarioDataMissing as exc:
            raise StopUser from exc

    @task(8)
    def browse_lists(self) -> None:
        selector = self.sequence % 6
        self.sequence += 1
        if selector == 0:
            self._items("/api/v1/ticketing/types", name="GET /api/v1/ticketing/types")
        elif selector == 1:
            self._items("/api/v1/experiences", name="GET /api/v1/experiences")
        elif selector == 2:
            self._items("/api/v1/shop/products", name="GET /api/v1/shop/products")
        elif selector == 3:
            self._items(
                "/api/v1/ticketing/orders",
                name="GET /api/v1/ticketing/orders",
                headers=self.auth_headers,
            )
        elif selector == 4:
            self._items(
                "/api/v1/reservations",
                name="GET /api/v1/reservations",
                headers=self.auth_headers,
            )
        else:
            self._items(
                "/api/v1/shop/orders",
                name="GET /api/v1/shop/orders",
                headers=self.auth_headers,
            )

    @task(2)
    def ticket_purchase(self) -> None:
        if self.ticket_done:
            self._items(
                "/api/v1/ticketing/orders",
                name="GET /api/v1/ticketing/orders",
                headers=self.auth_headers,
            )
            return
        types = self._items(
            "/api/v1/ticketing/types",
            name="GET /api/v1/ticketing/types",
        )
        ticket_type = self._required_item(
            types,
            scenario="ticket catalogue available",
            reason="ticket catalogue returned no usable ticket type",
        )
        visit_date = (date.today() + timedelta(days=1)).isoformat()
        slots = self._items(
            "/api/v1/ticketing/slots",
            params={"visit_date": visit_date, "ticket_type_id": str(ticket_type["id"])},
            name="GET /api/v1/ticketing/slots",
        )
        slot = self._required_item(
            slots,
            scenario="ticket inventory available",
            reason="ticket slots returned no remaining inventory",
            predicate=lambda item: int(item.get("remaining", 0)) > 0,
        )
        with self.client.post(
            "/api/v1/ticketing/orders",
            headers=self.auth_headers,
            json={
                "slot_id": slot["id"],
                "quantity": 1,
                "idempotency_key": self._key("ticket"),
            },
            name="POST /api/v1/ticketing/orders",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"ticket order returned HTTP {response.status_code}")
                return
            payload = self._json(response, required_key="id")
        if payload is None:
            return
        with self.client.post(
            f"/api/v1/ticketing/orders/{payload['id']}/pay",
            headers=self.auth_headers,
            json={"idempotency_key": self._key("ticket-pay")},
            name="POST /api/v1/ticketing/orders/[id]/pay",
            catch_response=True,
        ) as response:
            paid = (
                self._json(response, required_key="status") if response.status_code == 200 else None
            )
            if paid is not None and paid.get("status") == "PAID":
                self.ticket_done = True
            else:
                response.failure(
                    f"ticket payment returned HTTP {response.status_code} "
                    f"with status {None if paid is None else paid.get('status')!r}"
                )

    @task(2)
    def experience_reservation(self) -> None:
        if self.reservation_done:
            self._items(
                "/api/v1/reservations",
                name="GET /api/v1/reservations",
                headers=self.auth_headers,
            )
            return
        experiences = self._items(
            "/api/v1/experiences",
            name="GET /api/v1/experiences",
        )
        experience = self._required_item(
            experiences,
            scenario="reservation catalogue available",
            reason="experience catalogue returned no usable experience",
        )
        visit_date = (date.today() + timedelta(days=3)).isoformat()
        sessions = self._items(
            f"/api/v1/experiences/{experience['id']}/sessions",
            params={"date": visit_date},
            name="GET /api/v1/experiences/[id]/sessions",
        )
        session = self._required_item(
            sessions,
            scenario="reservation session inventory available",
            reason="experience sessions returned no remaining inventory",
            predicate=lambda item: int(item.get("remaining", 0)) > 0,
        )
        with self.client.post(
            "/api/v1/reservations",
            headers=self.auth_headers,
            json={
                "session_id": session["id"],
                "party_size": 1,
                "idempotency_key": self._key("reservation"),
            },
            name="POST /api/v1/reservations",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"reservation returned HTTP {response.status_code}")
                return
            payload = self._json(response, required_key="id")
        if payload is None:
            return
        with self.client.post(
            f"/api/v1/reservations/{payload['id']}/confirm",
            headers=self.auth_headers,
            json={"idempotency_key": self._key("reservation-confirm")},
            name="POST /api/v1/reservations/[id]/confirm",
            catch_response=True,
        ) as response:
            confirmed = (
                self._json(response, required_key="status") if response.status_code == 200 else None
            )
            if confirmed is not None and confirmed.get("status") == "CONFIRMED":
                self.reservation_done = True
            else:
                response.failure(
                    f"reservation confirmation returned HTTP {response.status_code} "
                    f"with status {None if confirmed is None else confirmed.get('status')!r}"
                )

    @task(2)
    def shop_checkout(self) -> None:
        if self.shop_done:
            self._items(
                "/api/v1/shop/orders",
                name="GET /api/v1/shop/orders",
                headers=self.auth_headers,
            )
            return
        products = self._items(
            "/api/v1/shop/products",
            name="GET /api/v1/shop/products",
        )
        product = self._required_item(
            products,
            scenario="shop inventory available",
            reason="shop catalogue returned no in-stock product",
            predicate=lambda item: int(item.get("stock", 0)) > 0,
        )
        with self.client.post(
            "/api/v1/shop/cart/items",
            headers=self.auth_headers,
            json={"product_id": product["id"], "quantity": 1},
            name="POST /api/v1/shop/cart/items",
            catch_response=True,
        ) as response:
            if response.status_code != 200 or self._json(response, required_key="items") is None:
                response.failure(f"cart update returned HTTP {response.status_code}")
                return
        with self.client.post(
            "/api/v1/shop/cart/checkout",
            headers=self.auth_headers,
            json={
                "delivery": {
                    "name": "压测游客",
                    "phone": "13800000000",
                    "province": "浙江省",
                    "city": "杭州市",
                    "address_line": "本地压测地址 1 号",
                },
                "idempotency_key": self._key("shop"),
            },
            name="POST /api/v1/shop/cart/checkout",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"shop checkout returned HTTP {response.status_code}")
                return
            payload = self._json(response, required_key="id")
        if payload is None:
            return
        with self.client.post(
            f"/api/v1/shop/orders/{payload['id']}/pay",
            headers=self.auth_headers,
            json={"idempotency_key": self._key("shop-pay")},
            name="POST /api/v1/shop/orders/[id]/pay",
            catch_response=True,
        ) as response:
            paid = (
                self._json(response, required_key="status") if response.status_code == 200 else None
            )
            if paid is not None and paid.get("status") == "PAID":
                self.shop_done = True
            else:
                response.failure(
                    f"shop payment returned HTTP {response.status_code} "
                    f"with status {None if paid is None else paid.get('status')!r}"
                )

    @task(2)
    def crowd_websocket(self) -> None:
        url = websocket_url(self.host, "/api/v1/guide/ws/crowd")
        started = perf_counter()
        connection: websocket.WebSocket | None = None
        raw = ""
        error: Exception | None = None
        try:
            connection = websocket.create_connection(url, timeout=WS_TIMEOUT_SECONDS)
            raw = str(connection.recv())
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("type") != "crowd.snapshot":
                raise ValueError("unexpected crowd WebSocket envelope")
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("sequence"), int):
                raise ValueError("crowd WebSocket envelope omitted its sequence")
        except Exception as exc:  # Locust must record protocol failures, not crash the user.
            error = exc
        finally:
            if connection is not None:
                connection.close()
        self.environment.events.request.fire(
            request_type="WS",
            name="/api/v1/guide/ws/crowd",
            response_time=(perf_counter() - started) * 1000,
            response_length=len(raw.encode()),
            exception=error,
        )

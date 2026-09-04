"""Run the MVP acceptance journey against a real HTTP/WebSocket server.

This command never imports the ASGI application.  Start Uvicorn separately, seed
the database, then run ``uv run tourism-smoke`` to prove the network boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import websocket


class SmokeFailure(RuntimeError):
    """An acceptance step returned an invalid status or contract."""


@dataclass(frozen=True, slots=True)
class SmokeConfig:
    base_url: str = "http://127.0.0.1:8000"
    username: str = "tourist_demo"
    password: str = "Tourism123!"
    admin_username: str = "admin_demo"
    admin_password: str = "Tourism123!"
    timeout_seconds: float = 10.0


def websocket_url(
    base_url: str,
    path: str,
    query: dict[str, str] | None = None,
) -> str:
    """Build a ws/wss URL without dropping an optional deployment prefix."""

    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base URL must be an absolute http:// or https:// URL")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    joined_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    return urlunsplit((scheme, parsed.netloc, joined_path, urlencode(query or {}), ""))


def require_object(payload: object, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{label}: expected a JSON object")
    return payload


def require_items(payload: object, *, label: str) -> list[dict[str, Any]]:
    body = require_object(payload, label=label)
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise SmokeFailure(f"{label}: expected a non-empty 'items' list")
    if not all(isinstance(item, dict) for item in items):
        raise SmokeFailure(f"{label}: every item must be a JSON object")
    return items


class SmokeRunner:
    """Stateful, fail-fast real-network acceptance journey."""

    def __init__(self, config: SmokeConfig) -> None:
        self.config = config
        self.run_id = uuid4().hex
        self.check_count = 0
        self.client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        self.tourist_token = ""
        self.admin_token = ""

    def close(self) -> None:
        self.client.close()

    def _pass(self, label: str) -> None:
        self.check_count += 1
        print(f"[PASS] {label}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        label: str,
        expected_status: int = 200,
        token: str | None = None,
        **kwargs: Any,
    ) -> tuple[httpx.Response, object]:
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise SmokeFailure(f"{label}: network request failed: {exc}") from exc
        if response.status_code != expected_status:
            detail = response.text.replace("\n", " ")[:500]
            raise SmokeFailure(
                f"{label}: expected HTTP {expected_status}, got {response.status_code}: {detail}"
            )
        if not response.content:
            payload: object = {}
        else:
            try:
                payload = response.json()
            except ValueError as exc:
                raise SmokeFailure(f"{label}: response was not valid JSON") from exc
        self._pass(label)
        return response, payload

    def _login(self, username: str, password: str, *, label: str) -> str:
        _, payload = self._request(
            "POST",
            "/api/v1/auth/login",
            label=label,
            json={"username": username, "password": password},
        )
        token = require_object(payload, label=label).get("access_token")
        if not isinstance(token, str) or not token:
            raise SmokeFailure(f"{label}: access_token was missing")
        return token

    def _key(self, operation: str) -> str:
        return f"smoke-{operation}-{self.run_id}"

    def system_and_auth(self) -> None:
        _, health = self._request("GET", "/health", label="health")
        if require_object(health, label="health").get("status") != "ok":
            raise SmokeFailure("health: status was not 'ok'")

        try:
            docs = self.client.get("/docs")
        except httpx.HTTPError as exc:
            raise SmokeFailure(f"OpenAPI docs: network request failed: {exc}") from exc
        if docs.status_code != 200 or "swagger" not in docs.text.lower():
            raise SmokeFailure("OpenAPI docs: Swagger UI was not served")
        self._pass("OpenAPI docs")

        _, capabilities = self._request(
            "GET", "/api/v1/meta/capabilities", label="capability metadata"
        )
        if "roles" not in require_object(capabilities, label="capability metadata"):
            raise SmokeFailure("capability metadata: roles were missing")

        registration_username = f"smoke_{self.run_id[:24]}"
        registration_password = f"Smoke{self.run_id[:16]}9"
        _, registration_payload = self._request(
            "POST",
            "/api/v1/auth/register",
            label="tourist registration",
            expected_status=201,
            json={
                "username": registration_username,
                "display_name": "Smoke Visitor",
                "password": registration_password,
            },
        )
        registration = require_object(registration_payload, label="tourist registration")
        registered_user = require_object(registration.get("user"), label="registered tourist")
        registered_token = registration.get("access_token")
        if registered_user.get("username") != registration_username or registered_user.get(
            "roles"
        ) != ["tourist"]:
            raise SmokeFailure("tourist registration: expected a normalized tourist identity")
        if not isinstance(registered_token, str) or not registered_token:
            raise SmokeFailure("tourist registration: access_token was missing")

        _, registered_profile = self._request(
            "GET",
            "/api/v1/users/me",
            label="registered tourist session",
            token=registered_token,
        )
        if (
            require_object(registered_profile, label="registered tourist session").get("username")
            != registration_username
        ):
            raise SmokeFailure("registered tourist session: wrong user returned")

        _, duplicate_payload = self._request(
            "POST",
            "/api/v1/auth/register",
            label="duplicate registration conflict",
            expected_status=409,
            json={
                "username": registration_username.upper(),
                "display_name": "Duplicate Visitor",
                "password": "DifferentVisitor456",
            },
        )
        duplicate_error = require_object(
            require_object(duplicate_payload, label="duplicate registration conflict").get("error"),
            label="duplicate registration error",
        )
        if duplicate_error.get("code") != "USERNAME_TAKEN":
            raise SmokeFailure("duplicate registration conflict: wrong error code")

        self.tourist_token = self._login(
            self.config.username,
            self.config.password,
            label="tourist login",
        )
        _, me = self._request(
            "GET",
            "/api/v1/users/me",
            label="authenticated profile",
            token=self.tourist_token,
        )
        if require_object(me, label="authenticated profile").get("username") != (
            self.config.username
        ):
            raise SmokeFailure("authenticated profile: wrong user returned")
        self.admin_token = self._login(
            self.config.admin_username,
            self.config.admin_password,
            label="administrator login",
        )

    def ticket_journey(self) -> None:
        _, type_payload = self._request("GET", "/api/v1/ticketing/types", label="ticket type list")
        ticket_type = require_items(type_payload, label="ticket type list")[0]
        slot: dict[str, Any] | None = None
        for day_offset in range(1, 8):
            visit_date = (date.today() + timedelta(days=day_offset)).isoformat()
            _, slot_payload = self._request(
                "GET",
                "/api/v1/ticketing/slots",
                label=f"ticket slots day +{day_offset}",
                params={"visit_date": visit_date, "ticket_type_id": ticket_type["id"]},
            )
            slots = require_object(slot_payload, label="ticket slots").get("items")
            if isinstance(slots, list):
                slot = next(
                    (
                        item
                        for item in slots
                        if isinstance(item, dict) and int(item.get("remaining", 0)) > 0
                    ),
                    None,
                )
            if slot is not None:
                break
        if slot is None:
            raise SmokeFailure("ticket slots: no sellable seeded slot found")

        self._request(
            "POST",
            "/api/v1/ticketing/quotes",
            label="ticket quote",
            json={"slot_id": slot["id"], "quantity": 1},
        )
        _, created_payload = self._request(
            "POST",
            "/api/v1/ticketing/orders",
            label="ticket order",
            expected_status=201,
            token=self.tourist_token,
            json={
                "slot_id": slot["id"],
                "quantity": 1,
                "idempotency_key": self._key("ticket-order"),
            },
        )
        created = require_object(created_payload, label="ticket order")
        _, paid_payload = self._request(
            "POST",
            f"/api/v1/ticketing/orders/{created['id']}/pay",
            label="ticket payment",
            token=self.tourist_token,
            json={"idempotency_key": self._key("ticket-pay")},
        )
        paid = require_object(paid_payload, label="ticket payment")
        tickets = paid.get("tickets")
        if paid.get("status") != "PAID" or not isinstance(tickets, list) or not tickets:
            raise SmokeFailure("ticket payment: paid order omitted an issued ticket")
        _, qr_payload = self._request(
            "GET",
            f"/api/v1/ticketing/tickets/{tickets[0]['id']}/qr",
            label="electronic ticket QR",
            token=self.tourist_token,
        )
        qr = require_object(qr_payload, label="electronic ticket QR")
        _, validation_payload = self._request(
            "POST",
            "/api/v1/ticketing/gate/validate",
            label="future-ticket gate window enforcement",
            expected_status=409,
            token=self.admin_token,
            json={
                "qr_data": qr["qr_data"],
                "request_id": self._key("gate"),
                "gate_code": "checkpoint-9-gate",
            },
        )
        validation_error = require_object(validation_payload, label="gate validation").get("error")
        if not isinstance(validation_error, dict) or validation_error.get("code") != (
            "TICKET_OUTSIDE_VALIDATION_WINDOW"
        ):
            raise SmokeFailure("gate validation: future-ticket rejection contract changed")

    def reservation_journey(self) -> dict[str, Any]:
        _, experience_payload = self._request("GET", "/api/v1/experiences", label="experience list")
        experiences = require_items(experience_payload, label="experience list")
        _, existing_payload = self._request(
            "GET",
            "/api/v1/reservations",
            label="existing reservation list",
            token=self.tourist_token,
        )
        existing = require_object(existing_payload, label="existing reservation list").get(
            "items", []
        )
        occupied_dates = {
            str(item.get("starts_at", ""))[:10]
            for item in existing
            if isinstance(item, dict) and item.get("status") in {"HELD", "CONFIRMED"}
        }
        selected_experience: dict[str, Any] | None = None
        selected_session: dict[str, Any] | None = None
        for experience in experiences:
            for day_offset in range(3, 8):
                candidate_date = (date.today() + timedelta(days=day_offset)).isoformat()
                if candidate_date in occupied_dates:
                    continue
                _, sessions_payload = self._request(
                    "GET",
                    f"/api/v1/experiences/{experience['id']}/sessions",
                    label=f"experience sessions day +{day_offset}",
                    params={"date": candidate_date},
                )
                sessions = require_object(sessions_payload, label="experience sessions").get(
                    "items"
                )
                if isinstance(sessions, list):
                    selected_session = next(
                        (
                            item
                            for item in sessions
                            if isinstance(item, dict) and int(item.get("remaining", 0)) > 0
                        ),
                        None,
                    )
                if selected_session is not None:
                    selected_experience = experience
                    break
            if selected_session is not None:
                break
        if selected_session is None or selected_experience is None:
            raise SmokeFailure("experience sessions: no reservable seeded session found")

        _, reservation_payload = self._request(
            "POST",
            "/api/v1/reservations",
            label="experience reservation",
            expected_status=201,
            token=self.tourist_token,
            json={
                "session_id": selected_session["id"],
                "party_size": 1,
                "idempotency_key": self._key("reservation"),
            },
        )
        reservation = require_object(reservation_payload, label="experience reservation")
        _, confirmed_payload = self._request(
            "POST",
            f"/api/v1/reservations/{reservation['id']}/confirm",
            label="reservation confirmation",
            token=self.tourist_token,
            json={"idempotency_key": self._key("reservation-confirm")},
        )
        if require_object(confirmed_payload, label="reservation confirmation").get("status") != (
            "CONFIRMED"
        ):
            raise SmokeFailure("reservation confirmation: status was not CONFIRMED")
        _, cancelled_payload = self._request(
            "POST",
            f"/api/v1/reservations/{reservation['id']}/cancel",
            label="reservation cancellation cleanup",
            token=self.tourist_token,
            json={
                "reason": "检查点九验收清理",
                "idempotency_key": self._key("reservation-cancel"),
            },
        )
        if (
            require_object(cancelled_payload, label="reservation cancellation cleanup").get(
                "status"
            )
            != "CANCELLED"
        ):
            raise SmokeFailure("reservation cancellation cleanup: status was not CANCELLED")
        queue_experience = next(
            (experience for experience in experiences if experience.get("kind") == "RIDE"),
            selected_experience,
        )
        return queue_experience

    def shop_journey(self) -> None:
        _, cart_payload = self._request(
            "GET", "/api/v1/shop/cart", label="shopping cart", token=self.tourist_token
        )
        existing_items = require_object(cart_payload, label="shopping cart").get("items", [])
        if isinstance(existing_items, list):
            for item in existing_items:
                if isinstance(item, dict) and "id" in item:
                    self._request(
                        "DELETE",
                        f"/api/v1/shop/cart/items/{item['id']}",
                        label="clear stale cart item",
                        token=self.tourist_token,
                    )

        _, product_payload = self._request(
            "GET", "/api/v1/shop/products", label="shop product list"
        )
        product = next(
            (
                item
                for item in require_items(product_payload, label="shop product list")
                if int(item.get("stock", 0)) > 0
            ),
            None,
        )
        if product is None:
            raise SmokeFailure("shop product list: no in-stock product found")
        self._request(
            "POST",
            "/api/v1/shop/cart/items",
            label="add shop cart item",
            token=self.tourist_token,
            json={"product_id": product["id"], "quantity": 1},
        )
        _, order_payload = self._request(
            "POST",
            "/api/v1/shop/cart/checkout",
            label="shop checkout",
            expected_status=201,
            token=self.tourist_token,
            json={
                "delivery": {
                    "name": "验收游客",
                    "phone": "13800000000",
                    "province": "浙江省",
                    "city": "杭州市",
                    "address_line": "检查点九验收地址 1 号",
                },
                "idempotency_key": self._key("shop-order"),
            },
        )
        order = require_object(order_payload, label="shop checkout")
        _, paid_payload = self._request(
            "POST",
            f"/api/v1/shop/orders/{order['id']}/pay",
            label="shop payment",
            token=self.tourist_token,
            json={"idempotency_key": self._key("shop-pay")},
        )
        if require_object(paid_payload, label="shop payment").get("status") != "PAID":
            raise SmokeFailure("shop payment: status was not PAID")

    def checkpoint8_journey(self) -> None:
        _, pack_payload = self._request(
            "GET",
            "/api/v1/offline/packs/latest",
            label="offline pack",
            token=self.tourist_token,
        )
        pack = require_object(pack_payload, label="offline pack")
        manifest_response, manifest_payload = self._request(
            "GET",
            f"/api/v1/offline/packs/{pack['id']}/manifest",
            label="offline manifest",
            token=self.tourist_token,
        )
        manifest = require_object(manifest_payload, label="offline manifest")
        assets_value = manifest.get("assets")
        if (
            not isinstance(assets_value, list)
            or not assets_value
            or not all(isinstance(item, dict) for item in assets_value)
        ):
            raise SmokeFailure("offline manifest: expected non-empty asset objects")
        assets: list[dict[str, Any]] = assets_value
        etag = manifest_response.headers.get("etag")
        if not etag:
            raise SmokeFailure("offline manifest: ETag header was missing")
        self._request(
            "GET",
            f"/api/v1/offline/packs/{pack['id']}/manifest",
            label="offline manifest revalidation",
            expected_status=304,
            token=self.tourist_token,
            headers={"If-None-Match": etag},
        )
        self._request(
            "GET",
            f"/api/v1/offline/packs/{pack['id']}/assets/{assets[0]['id']}",
            label="offline asset",
            token=self.tourist_token,
        )

        device_id = f"smoke-{self.run_id[:16]}"
        _, status_payload = self._request(
            "GET",
            "/api/v1/offline/sync/status",
            label="offline sync status",
            token=self.tourist_token,
            params={"device_id": device_id},
        )
        sync_status = require_object(status_payload, label="offline sync status")
        _, push_payload = self._request(
            "POST",
            "/api/v1/offline/sync/push",
            label="offline sync push",
            token=self.tourist_token,
            json={
                "device_id": device_id,
                "base_cursor": sync_status["cursor"],
                "mutations": [
                    {
                        "client_mutation_id": self._key("offline-note"),
                        "client_version": 1,
                        "entity_type": "NOTE",
                        "entity_id": f"note-{self.run_id[:16]}",
                        "operation": "UPSERT",
                        "payload": {"title": "检查点九", "text": "真实网络验收"},
                    }
                ],
            },
        )
        cursor = require_object(push_payload, label="offline sync push").get("server_cursor")
        self._request(
            "GET",
            "/api/v1/offline/sync/pull",
            label="offline sync pull",
            token=self.tourist_token,
            params={"device_id": device_id, "cursor": sync_status["cursor"]},
        )
        if not isinstance(cursor, str):
            raise SmokeFailure("offline sync push: server_cursor was missing")

        _, resources_payload = self._request(
            "GET",
            "/api/v1/emergency/resources",
            label="emergency resources",
            token=self.tourist_token,
        )
        resources = require_items(resources_payload, label="emergency resources")
        self._request(
            "GET",
            "/api/v1/emergency/bulletins",
            label="emergency bulletins",
            token=self.tourist_token,
        )
        _, sos_payload = self._request(
            "POST",
            "/api/v1/emergency/sos",
            label="demo SOS persistence",
            expected_status=201,
            token=self.tourist_token,
            json={
                "kind": "OTHER",
                "message": "检查点九真实网络演示请求",
                "node_id": resources[0].get("node_id"),
                "idempotency_key": self._key("sos"),
            },
        )
        sos = require_object(sos_payload, label="demo SOS persistence")
        if sos.get("is_demo") is not True or sos.get("real_dispatch") is not False:
            raise SmokeFailure("demo SOS persistence: real-world boundary was not explicit")
        self._request("GET", "/api/v1/passport", label="digital passport", token=self.tourist_token)
        self._request(
            "GET", "/api/v1/green/tasks", label="green task list", token=self.tourist_token
        )

    def _websocket(
        self,
        path: str,
        *,
        label: str,
        expected_type: str | set[str],
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = websocket_url(self.config.base_url, path, query)
        connection: websocket.WebSocket | None = None
        try:
            connection = websocket.create_connection(url, timeout=self.config.timeout_seconds)
            initial = require_object(json.loads(str(connection.recv())), label=label)
            expected_types = {expected_type} if isinstance(expected_type, str) else expected_type
            if initial.get("type") not in expected_types:
                raise SmokeFailure(
                    f"{label}: expected one of {sorted(expected_types)!r}, "
                    f"got {initial.get('type')!r}"
                )
            return initial
        except (OSError, ValueError, websocket.WebSocketException) as exc:
            raise SmokeFailure(f"{label}: WebSocket exchange failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _crowd_websocket(self) -> None:
        label = "crowd WebSocket initial plus publisher tick"
        url = websocket_url(self.config.base_url, "/api/v1/guide/ws/crowd")
        connection: websocket.WebSocket | None = None
        try:
            connection = websocket.create_connection(url, timeout=self.config.timeout_seconds)
            initial = require_object(json.loads(str(connection.recv())), label=label)
            update = require_object(json.loads(str(connection.recv())), label=label)
            if initial.get("type") != "crowd.snapshot" or update.get("type") != "crowd.snapshot":
                raise SmokeFailure(f"{label}: unexpected event type")
            initial_data = require_object(initial.get("data"), label=label)
            update_data = require_object(update.get("data"), label=label)
            initial_sequence = initial_data.get("sequence")
            update_sequence = update_data.get("sequence")
            if not isinstance(initial_sequence, int) or not isinstance(update_sequence, int):
                raise SmokeFailure(f"{label}: sequence was missing")
            if update_sequence <= initial_sequence or initial.get("id") == update.get("id"):
                raise SmokeFailure(f"{label}: later publisher tick did not advance")
            self._pass(label)
        except (OSError, ValueError, websocket.WebSocketException) as exc:
            raise SmokeFailure(f"{label}: WebSocket exchange failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _assert_consumed_queue_ticket(self, queue_id: str, ticket: str) -> None:
        label = "queue WebSocket ticket is one-use"
        url = websocket_url(
            self.config.base_url,
            f"/api/v1/ws/queues/{queue_id}",
            {"ticket": ticket},
        )
        connection: websocket.WebSocket | None = None
        try:
            connection = websocket.create_connection(url, timeout=self.config.timeout_seconds)
            payload = connection.recv()
        except websocket.WebSocketBadStatusException as exc:
            # Closing with 4401 before accept is represented by Uvicorn as a
            # rejected HTTP WebSocket handshake.
            if exc.status_code != 403:
                raise SmokeFailure(
                    f"{label}: expected rejected handshake, got HTTP {exc.status_code}"
                ) from exc
            self._pass(label)
            return
        except websocket.WebSocketConnectionClosedException:
            self._pass(label)
            return
        finally:
            if connection is not None:
                connection.close()
        raise SmokeFailure(f"{label}: consumed ticket unexpectedly yielded {payload!r}")

    def _support_websocket(self, conversation_id: str, ticket: str) -> None:
        label = "support WebSocket human plus demo-bot messages"
        url = websocket_url(
            self.config.base_url,
            f"/api/v1/ws/support/{conversation_id}",
            {"ticket": ticket},
        )
        connection: websocket.WebSocket | None = None
        sent_content = "检查点九 WebSocket 消息"
        messages: dict[str, dict[str, Any]] = {}
        try:
            connection = websocket.create_connection(url, timeout=self.config.timeout_seconds)
            initial = require_object(json.loads(str(connection.recv())), label=label)
            if initial.get("type") != "support.updated":
                raise SmokeFailure(f"{label}: initial support.updated event was missing")
            connection.send(
                json.dumps(
                    {
                        "type": "message.send",
                        "data": {
                            "content": sent_content,
                            "idempotency_key": self._key("support-message"),
                        },
                    },
                    ensure_ascii=False,
                )
            )
            while set(messages) != {"TOURIST", "BOT"}:
                envelope = require_object(json.loads(str(connection.recv())), label=label)
                if envelope.get("type") != "support.message":
                    raise SmokeFailure(f"{label}: unexpected event {envelope.get('type')!r}")
                data = require_object(envelope.get("data"), label=label)
                message = require_object(data.get("message"), label=label)
                sender_type = message.get("sender_type")
                if sender_type not in {"TOURIST", "BOT"}:
                    raise SmokeFailure(f"{label}: unexpected sender_type {sender_type!r}")
                messages[str(sender_type)] = message
            tourist = messages["TOURIST"]
            bot = messages["BOT"]
            if (
                tourist.get("content") != sent_content
                or tourist.get("provider") != "human"
                or tourist.get("is_demo") is not False
            ):
                raise SmokeFailure(f"{label}: tourist message provenance was invalid")
            if (
                not isinstance(bot.get("content"), str)
                or not bot["content"]
                or bot.get("provider") != "demo_support_bot"
                or bot.get("is_demo") is not True
            ):
                raise SmokeFailure(f"{label}: bot message provenance was invalid")
            sequences = [tourist.get("sequence"), bot.get("sequence")]
            if (
                not all(isinstance(value, int) for value in sequences)
                or bot["sequence"] <= tourist["sequence"]
            ):
                raise SmokeFailure(f"{label}: message sequence did not increase")
            self._pass(label)
        except (OSError, ValueError, websocket.WebSocketException) as exc:
            raise SmokeFailure(f"{label}: WebSocket exchange failed: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        _, persisted_payload = self._request(
            "GET",
            f"/api/v1/support/conversations/{conversation_id}/messages",
            label="support WebSocket messages persisted",
            token=self.tourist_token,
        )
        persisted = require_items(persisted_payload, label="support WebSocket messages persisted")
        persisted_by_id = {str(item.get("id")): item for item in persisted}
        expected_ids = {str(message["id"]) for message in messages.values()}
        if not expected_ids.issubset(persisted_by_id):
            raise SmokeFailure("support WebSocket messages persisted: message IDs were missing")
        for message in messages.values():
            persisted_message = persisted_by_id[str(message["id"])]
            if persisted_message.get("content") != message.get("content") or persisted_message.get(
                "sender_type"
            ) != message.get("sender_type"):
                raise SmokeFailure(
                    "support WebSocket messages persisted: persisted content changed"
                )
        persisted_sequences = [persisted_by_id[item_id]["sequence"] for item_id in expected_ids]
        expected_sequences = [
            messages["TOURIST"]["sequence"],
            messages["BOT"]["sequence"],
        ]
        if sorted(persisted_sequences) != expected_sequences:
            raise SmokeFailure("support WebSocket messages persisted: sequences changed")

    def realtime_journeys(self, queue_experience: dict[str, Any]) -> None:
        self._crowd_websocket()

        _, queue_payload = self._request(
            "POST",
            "/api/v1/queues",
            label="virtual queue join",
            expected_status=201,
            token=self.tourist_token,
            json={
                "experience_id": queue_experience["id"],
                "party_size": 1,
                "idempotency_key": self._key("queue"),
            },
        )
        queue = require_object(queue_payload, label="virtual queue join")
        try:
            _, ticket_payload = self._request(
                "POST",
                "/api/v1/ws-tickets",
                label="queue WebSocket ticket",
                token=self.tourist_token,
                json={"channel_type": "queue", "channel_id": queue["id"]},
            )
            ticket = require_object(ticket_payload, label="queue WebSocket ticket")
            queue_event = self._websocket(
                f"/api/v1/ws/queues/{queue['id']}",
                label="queue WebSocket",
                expected_type={
                    "queue.updated",
                    "nearby.recommended",
                    "itinerary.replan_available",
                },
                query={"ticket": str(ticket["ticket"])},
            )
            queue_data = require_object(queue_event.get("data"), label="queue WebSocket")
            queue_state = require_object(queue_data.get("queue"), label="queue WebSocket")
            if queue_state.get("id") != queue["id"]:
                raise SmokeFailure("queue WebSocket: event belonged to another queue")
            self._pass("queue WebSocket")
            self._assert_consumed_queue_ticket(queue["id"], str(ticket["ticket"]))
        finally:
            self._request(
                "DELETE",
                f"/api/v1/queues/{queue['id']}",
                label="virtual queue leave",
                token=self.tourist_token,
                json={"idempotency_key": self._key("queue-leave")},
            )

        _, conversation_payload = self._request(
            "POST",
            "/api/v1/support/conversations",
            label="support conversation",
            expected_status=201,
            token=self.tourist_token,
            json={"subject": "检查点九实时客服验收"},
        )
        conversation = require_object(conversation_payload, label="support conversation")
        _, support_ticket_payload = self._request(
            "POST",
            "/api/v1/support/ws-tickets",
            label="support WebSocket ticket",
            token=self.tourist_token,
            json={"conversation_id": conversation["id"]},
        )
        support_ticket = require_object(support_ticket_payload, label="support WebSocket ticket")
        self._support_websocket(conversation["id"], str(support_ticket["ticket"]))

    def run(self) -> int:
        self.system_and_auth()
        self.ticket_journey()
        queue_experience = self.reservation_journey()
        self.shop_journey()
        self.checkpoint8_journey()
        self.realtime_journeys(queue_experience)
        return self.check_count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("TOURISM_SMOKE_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--username", default=os.getenv("TOURISM_SMOKE_USERNAME", "tourist_demo"))
    parser.add_argument("--password", default=os.getenv("TOURISM_SMOKE_PASSWORD", "Tourism123!"))
    parser.add_argument(
        "--admin-username",
        default=os.getenv("TOURISM_SMOKE_ADMIN_USERNAME", "admin_demo"),
    )
    parser.add_argument(
        "--admin-password",
        default=os.getenv("TOURISM_SMOKE_ADMIN_PASSWORD", "Tourism123!"),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("TOURISM_SMOKE_TIMEOUT_SECONDS", "10")),
    )
    return parser


def run() -> None:
    """Console-script adapter with a concise non-zero failure."""

    args = _parser().parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    runner = SmokeRunner(
        SmokeConfig(
            base_url=args.base_url,
            username=args.username,
            password=args.password,
            admin_username=args.admin_username,
            admin_password=args.admin_password,
            timeout_seconds=args.timeout,
        )
    )
    try:
        checks = runner.run()
    except SmokeFailure as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        runner.close()
    print(f"Real-network smoke passed ({checks} checks).")


if __name__ == "__main__":
    run()

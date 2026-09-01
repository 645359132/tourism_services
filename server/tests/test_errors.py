"""Stable API error envelope tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import AppError


def test_not_found_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/missing", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found"},
        "request_id": "request-123",
    }


def test_app_error_preserves_safe_details(application: FastAPI) -> None:
    @application.get("/expected-error")
    async def expected_error() -> None:
        raise AppError(
            status_code=409,
            code="STATE_CONFLICT",
            message="State conflict",
            details={"state": "closed"},
        )

    with TestClient(application) as client:
        response = client.get("/expected-error")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "STATE_CONFLICT",
        "message": "State conflict",
        "details": {"state": "closed"},
    }


def test_validation_error_uses_error_envelope(application: FastAPI) -> None:
    @application.get("/number/{value}")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    with TestClient(application) as client:
        response = client.get("/number/not-an-integer")

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"][0]["loc"] == ["path", "value"]


def test_unexpected_error_is_hidden_and_correlated(application: FastAPI) -> None:
    @application.get("/unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError("sensitive internal detail")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/unexpected-error",
            headers={"X-Request-ID": "unexpected-123"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "unexpected-123"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
        },
        "request_id": "unexpected-123",
    }

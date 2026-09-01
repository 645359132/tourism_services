"""Health endpoint and HTTP middleware tests."""

from fastapi.testclient import TestClient


def test_health_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Tourism Test Service",
        "version": "0.1.0",
        "environment": "test",
    }
    assert response.headers["X-Request-ID"]


def test_cors_preflight_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "https://client.example"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"

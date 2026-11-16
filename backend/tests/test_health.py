"""Health checks : forme du contrat, dépendances, en-tête de mock."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_contract_shape(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "version", "dependencies"}
    assert body["status"] in ("ok", "degraded")
    assert body["version"] == "0.1.0"
    assert set(body["dependencies"]) == {"database", "redis", "llm"}
    assert body["dependencies"]["database"] == "ok"
    # Redis absent dans l'environnement de test -> dépendance signalée dégradée.
    assert body["dependencies"]["redis"] in ("ok", "degraded")


def test_health_alias_without_prefix(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/health").json()["dependencies"]["database"] == "ok"


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/api/v1/health").status_code == 200


def test_mock_headers_present_without_api_keys(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Kwes-Mock") == "1"
    providers = response.headers.get("X-Kwes-Mock-Providers", "")
    assert "deepseek" in providers and "elevenlabs" in providers


def test_request_id_header_present(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Request-ID")

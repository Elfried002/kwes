"""Authentification JWT : absence, invalide, expiré, mauvais secret, profil auto."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import create_dev_token


def _error_codes(response) -> dict:
    body = response.json()
    assert "error" in body, body
    error = body["error"]
    assert set(error) >= {"code", "message", "details", "request_id", "retryable"}
    return error


def test_missing_authorization_returns_unauthenticated(client: TestClient) -> None:
    response = client.get("/api/v1/conversations")
    assert response.status_code == 401
    assert _error_codes(response)["code"] == "UNAUTHENTICATED"


def test_invalid_token_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert _error_codes(response)["code"] == "UNAUTHENTICATED"


def test_expired_token_rejected(settings: Settings, client: TestClient) -> None:
    token = create_dev_token(uuid.uuid4(), "expired@kwes.local", settings, ttl_minutes=-5)
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert _error_codes(response)["code"] == "UNAUTHENTICATED"


def test_wrong_secret_rejected(settings: Settings, client: TestClient) -> None:
    token = create_dev_token(
        uuid.uuid4(), "forged@kwes.local", settings, secret="another-secret-entirely"
    )
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_unknown_scheme_rejected(client: TestClient) -> None:
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": "Basic abcdef"}
    )
    assert response.status_code == 401


def test_valid_token_creates_profile(
    client: TestClient, headers: dict[str, str], user_id: uuid.UUID, db_session_factory
) -> None:
    assert client.get("/api/v1/conversations", headers=headers).status_code == 200
    with db_session_factory() as session:
        from app.db.models import Profile

        profile = session.get(Profile, user_id)
        assert profile is not None
        assert profile.id == user_id


def test_same_user_reuses_profile(
    client: TestClient, headers: dict[str, str], user_id: uuid.UUID, db_session_factory
) -> None:
    client.post("/api/v1/conversations", json={"title": "A"}, headers=headers)
    client.post("/api/v1/conversations", json={"title": "B"}, headers=headers)
    with db_session_factory() as session:
        from sqlalchemy import func, select

        from app.db.models import Profile

        count = session.execute(
            select(func.count(Profile.id)).where(Profile.id == user_id)
        ).scalar_one()
    assert count == 1


def test_rate_limit_returns_429(settings: Settings, fake_fetcher) -> None:
    from app.main import create_app

    limited = settings.model_copy(
        update={"rate_limit_enabled": True, "rate_limit_chat_per_minute": 2}
    )
    application = create_app(limited)
    application.state.fetcher = fake_fetcher
    with TestClient(application) as local_client:
        token = create_dev_token(uuid.uuid4(), "rl@kwes.local", limited)
        headers = {"Authorization": f"Bearer {token}"}
        codes = []
        for _ in range(4):
            response = local_client.post(
                "/api/v1/chat", json={"message": "bonjour", "mode": "direct"}, headers=headers
            )
            codes.append(response.status_code)
        assert 429 in codes
        last = response.json()
        assert last["error"]["code"] == "RATE_LIMITED"
        assert response.headers.get("Retry-After")


def test_unknown_route_uses_contract_error_format(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert _error_codes(response)["code"] == "NOT_FOUND"


@pytest.mark.parametrize("token", ["", "Bearer"])
def test_empty_bearer_rejected(client: TestClient, token: str) -> None:
    response = client.get("/api/v1/conversations", headers={"Authorization": token})
    assert response.status_code == 401

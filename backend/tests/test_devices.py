"""Tests des connecteurs d'appareil : enregistrement, jeton, capacités, révocation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _register(client: TestClient, headers: dict, connector_id: str = "android-test") -> dict:
    r = client.post(
        "/api/v1/devices",
        json={
            "connector_id": connector_id,
            "platform": "android",
            "connector_version": "0.1.0",
            "capabilities": ["notifications.read", "contacts.read"],
            "permissions": {"notifications.read": "granted"},
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_registration_requires_user_session(client: TestClient):
    r = client.post("/api/v1/devices", json={"connector_id": "x-android", "platform": "android"})
    assert r.status_code == 401


def test_register_returns_token_once_and_hides_it_later(client: TestClient, headers):
    data = _register(client, headers)
    assert data["token"] and len(data["token"]) >= 32
    assert data["capabilities"] == ["notifications.read", "contacts.read"]

    listing = client.get("/api/v1/devices", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert len(body) == 1
    assert "token" not in body[0]


def test_heartbeat_requires_valid_device_token(client: TestClient, headers):
    data = _register(client, headers)

    ok = client.post(
        "/api/v1/device/heartbeat",
        json={"permissions": {"contacts.read": "granted"}},
        headers={"X-Device-Token": data["token"]},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    bad = client.post("/api/v1/device/heartbeat", json={}, headers={"X-Device-Token": "faux"})
    assert bad.status_code == 401


def test_revoked_connector_is_rejected_immediately(client: TestClient, headers):
    data = _register(client, headers)
    token = data["token"]

    revoke = client.delete(f"/api/v1/devices/{data['id']}", headers=headers)
    assert revoke.status_code == 204

    after = client.post("/api/v1/device/heartbeat", json={}, headers={"X-Device-Token": token})
    assert after.status_code in (401, 403)


def test_user_cannot_revoke_another_users_connector(client: TestClient, headers, headers_other):
    data = _register(client, headers)
    r = client.delete(f"/api/v1/devices/{data['id']}", headers=headers_other)
    assert r.status_code == 404


def test_registering_twice_rotates_token(client: TestClient, headers):
    first = _register(client, headers, connector_id="android-rotate")
    second = _register(client, headers, connector_id="android-rotate")
    assert second["id"] == first["id"]
    assert second["token"] != first["token"]

    old = client.post(
        "/api/v1/device/heartbeat", json={}, headers={"X-Device-Token": first["token"]}
    )
    assert old.status_code == 401

    new = client.post(
        "/api/v1/device/heartbeat", json={}, headers={"X-Device-Token": second["token"]}
    )
    assert new.status_code == 200

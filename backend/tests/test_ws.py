"""WebSocket : authentification, origin, heartbeat, diffusion d'événements."""

from __future__ import annotations

import queue
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_dev_token


def _collect(
    websocket, *, until=None, timeout: float = 10.0
) -> list[dict]:
    """Lecture bornée (thread lecteur + file) : jamais de blocage de la suite."""
    inbox: queue.Queue[dict] = queue.Queue()

    def reader() -> None:
        try:
            while True:
                inbox.put(websocket.receive_json())
        except Exception as exc:  # socket fermée
            inbox.put({"event": "__closed__", "data": str(exc)})

    threading.Thread(target=reader, daemon=True).start()
    events: list[dict] = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(events) < 40:
        try:
            message = inbox.get(timeout=max(0.1, deadline - time.time()))
        except queue.Empty:
            break
        events.append(message)
        if message["event"] == "__closed__":
            break
        if until is not None and until(message):
            break
    return events


def test_ws_requires_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/v1/ws") as websocket:
            websocket.receive_json()
    assert exc.value.code == 1008


def test_ws_rejects_invalid_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws?token=not-a-jwt") as websocket:
            websocket.receive_json()


def test_ws_rejects_untrusted_origin(client: TestClient, settings, user_id: uuid.UUID) -> None:
    token = create_dev_token(user_id, "ws@kwes.local", settings)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/v1/ws?token={token}", headers={"origin": "http://evil.example"}
        ) as websocket:
            websocket.receive_json()


def test_ws_accepts_allowed_origin(client: TestClient, settings, user_id: uuid.UUID) -> None:
    token = create_dev_token(user_id, "ws@kwes.local", settings)
    with client.websocket_connect(
        f"/api/v1/ws?token={token}", headers={"origin": "http://127.0.0.1:5173"}
    ) as websocket:
        message = websocket.receive_json()
        assert message["event"] == "system.status"
        assert message["data"]["status"] == "connected"


def test_ws_envelope_and_ping(client: TestClient, settings, user_id: uuid.UUID) -> None:
    token = create_dev_token(user_id, "ws@kwes.local", settings)
    with client.websocket_connect(f"/api/v1/ws?token={token}") as websocket:
        first = websocket.receive_json()
        assert set(first) == {"event", "event_id", "timestamp", "data"}
        assert first["timestamp"].endswith("Z")
        uuid.UUID(first["event_id"])
        assert first["data"]["mock_providers"] == ["deepseek", "gemini"]

        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["event"] == "system.status"
        assert pong["data"]["pong"] is True


def test_ws_receives_task_events(
    client: TestClient, settings, user_id: uuid.UUID, headers: dict[str, str]
) -> None:
    token = create_dev_token(user_id, "ws@kwes.local", settings)
    with client.websocket_connect(f"/api/v1/ws?token={token}") as websocket:
        assert websocket.receive_json()["event"] == "system.status"

        response = client.post(
            "/api/v1/chat",
            json={"message": "Structure un plan de lancement", "mode": "mission"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        task_id = response.json()["task_id"]

        events = _collect(
            websocket,
            until=lambda event: event["event"] == "notification.created",
        )
        names = [event["event"] for event in events]
        assert "task.created" in names, names
        assert "task.step.started" in names, names

        terminal = [
            event
            for event in events
            if event["event"] == "task.updated" and event["data"].get("status") == "completed"
        ]
        assert terminal, names
        assert terminal[0]["data"]["task_id"] == task_id
        assert terminal[0]["data"]["progress"] == 100
        assert "notification.created" in names, names

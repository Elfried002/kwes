"""Conversations : CRUD, messages, suppression et données dérivées."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db.models import Conversation, Message, Task


def test_conversation_crud(client: TestClient, headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/conversations",
        json={"title": "Veille marché", "language": "fr"},
        headers=headers,
    )
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] == "Veille marché"
    assert conversation["language"] == "fr"

    fetched = client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == conversation["id"]

    listing = client.get("/api/v1/conversations", headers=headers)
    assert listing.status_code == 200
    assert listing.headers["X-Total-Count"] == "1"
    assert listing.json()[0]["message_count"] == 0

    deleted = client.delete(f"/api/v1/conversations/{conversation['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).status_code == 404


def test_delete_conversation_removes_messages_and_detaches_tasks(
    client: TestClient,
    headers: dict[str, str],
    wait_task,
    db_session_factory,
) -> None:
    chat = client.post(
        "/api/v1/chat",
        json={"message": "Prépare un plan de lancement", "mode": "mission"},
        headers=headers,
    ).json()
    wait_task(chat["task_id"])

    response = client.delete(f"/api/v1/conversations/{chat['conversation_id']}", headers=headers)
    assert response.status_code == 204

    with db_session_factory() as session:
        conversation_id = uuid.UUID(chat["conversation_id"])
        assert session.get(Conversation, conversation_id) is None
        remaining = session.query(Message).filter_by(conversation_id=conversation_id).count()
        assert remaining == 0
        task = session.get(Task, uuid.UUID(chat["task_id"]))
        assert task is not None and task.conversation_id is None

    assert client.get("/api/v1/conversations", headers=headers).json() == []


def test_messages_pagination(client: TestClient, headers: dict[str, str]) -> None:
    chat = client.post(
        "/api/v1/chat",
        json={"message": "Bonjour Kwes, peux-tu te présenter ?", "mode": "direct"},
        headers=headers,
    ).json()
    first_page = client.get(
        f"/api/v1/conversations/{chat['conversation_id']}/messages",
        params={"limit": 1},
        headers=headers,
    )
    assert first_page.status_code == 200
    assert len(first_page.json()) == 1
    assert first_page.headers["X-Total-Count"] == "2"

"""Isolation multi-tenant : critère bloquant de livraison.

Chaque test négatif doit échouer comme prévu : un utilisateur d'un tenant ne
doit jamais atteindre les données d'un autre, ni par liste, ni par identifiant
deviné, ni en réclamant un tenant dont il n'est pas membre.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient


def _tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    response = client.get("/api/v1/tenants", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows, "un espace personnel doit exister dès la première requête"
    return rows[0]["id"]


def test_personal_tenant_is_created_and_owned(client: TestClient, headers: dict[str, str], user_id: uuid.UUID) -> None:
    response = client.get("/api/v1/tenants", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    tenant = rows[0]
    assert tenant["role"] == "owner"
    assert tenant["is_personal"] is True
    assert tenant["id"] == str(user_id)
    assert tenant["members"] == 1


def test_conversations_are_isolated(
    client: TestClient, headers: dict[str, str], headers_other: dict[str, str]
) -> None:
    created = client.post("/api/v1/conversations", json={"title": "Privé A"}, headers=headers)
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    # B ne voit rien dans sa liste…
    listed = client.get("/api/v1/conversations", headers=headers_other)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == []

    # …et un identifiant deviné renvoie 404, pas 403 (aucune fuite d'existence).
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers_other).status_code == 404
    assert (
        client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers_other).status_code
        == 404
    )
    assert client.delete(f"/api/v1/conversations/{conversation_id}", headers=headers_other).status_code == 404

    # A continue de la voir.
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=headers).status_code == 200


def test_chat_refuses_foreign_conversation(
    client: TestClient, headers: dict[str, str], headers_other: dict[str, str]
) -> None:
    created = client.post("/api/v1/conversations", json={"title": "A"}, headers=headers)
    conversation_id = created.json()["id"]

    response = client.post(
        "/api/v1/chat",
        json={"message": "Bonjour", "conversation_id": conversation_id},
        headers=headers_other,
    )
    assert response.status_code == 404, response.text


def test_tasks_are_isolated(
    client: TestClient, headers: dict[str, str], headers_other: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/tasks",
        json={"goal": "Analyser le marché des fintechs", "title": "Veille"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    assert client.get(f"/api/v1/tasks/{task_id}", headers=headers_other).status_code == 404
    assert client.post(f"/api/v1/tasks/{task_id}/cancel", headers=headers_other).status_code == 404
    listed = client.get("/api/v1/tasks", headers=headers_other)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == []


def test_foreign_tenant_header_is_rejected(
    client: TestClient, headers: dict[str, str], headers_other: dict[str, str]
) -> None:
    tenant_a = _tenant_id(client, headers)

    response = client.get(
        "/api/v1/conversations", headers={**headers_other, "X-Tenant-Id": tenant_a}
    )
    assert response.status_code == 404, response.text

    invalid = client.get("/api/v1/conversations", headers={**headers_other, "X-Tenant-Id": "pas-un-uuid"})
    assert invalid.status_code == 404


def test_second_tenant_scopes_its_own_data(client: TestClient, headers: dict[str, str]) -> None:
    personal = _tenant_id(client, headers)
    client.post("/api/v1/conversations", json={"title": "Perso"}, headers=headers)

    created = client.post("/api/v1/tenants", json={"name": "Équipe Zawena"}, headers=headers)
    assert created.status_code == 201, created.text
    team = created.json()["id"]
    assert created.json()["role"] == "owner"

    # Dans l'espace personnel : une conversation. Dans l'équipe : aucune.
    personal_rows = client.get("/api/v1/conversations", headers={**headers, "X-Tenant-Id": personal})
    team_rows = client.get("/api/v1/conversations", headers={**headers, "X-Tenant-Id": team})
    assert len(personal_rows.json()) == 1
    assert team_rows.json() == []

    team_conversation = client.post(
        "/api/v1/conversations", json={"title": "Équipe"}, headers={**headers, "X-Tenant-Id": team}
    )
    assert team_conversation.status_code == 201
    team_conversation_id = team_conversation.json()["id"]

    # Elle n'apparaît pas dans l'espace personnel.
    personal_after = client.get("/api/v1/conversations", headers={**headers, "X-Tenant-Id": personal})
    assert team_conversation_id not in [row["id"] for row in personal_after.json()]

    # Un identifiant de l'équipe, lu depuis l'espace personnel, renvoie 404.
    cross = client.get(
        f"/api/v1/conversations/{team_conversation_id}", headers={**headers, "X-Tenant-Id": personal}
    )
    assert cross.status_code == 404


def test_current_tenant_reports_role_and_settings(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/api/v1/tenants/current", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["role"] == "owner"
    assert body["can_manage"] is True
    assert body["settings"]["locale"] == "fr"

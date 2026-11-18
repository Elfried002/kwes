"""Isolation entre utilisateurs : aucune fuite de conversation, mission, mémoire, etc."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db.models import Memory


def test_conversations_are_isolated(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
    user_id: uuid.UUID,
    other_user_id: uuid.UUID,
) -> None:
    created = client.post(
        "/api/v1/conversations", json={"title": "Secrète"}, headers=headers
    ).json()
    assert client.get("/api/v1/conversations", headers=headers_other).json() == []
    assert client.get(f"/api/v1/conversations/{created['id']}", headers=headers_other).status_code == 404
    assert (
        client.get(f"/api/v1/conversations/{created['id']}/messages", headers=headers_other).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/conversations/{created['id']}", headers=headers_other).status_code
        == 404
    )


def test_memory_is_isolated(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
    user_id: uuid.UUID,
    other_user_id: uuid.UUID,
    db_session_factory,
) -> None:
    with db_session_factory() as session:
        # Depuis la migration 0013, chaque ligne porte son espace de travail ;
        # l'espace personnel d'un utilisateur porte son identifiant.
        mine = Memory(user_id=user_id, tenant_id=user_id, category="semantic", content="Mon fournisseur préféré")
        theirs = Memory(user_id=other_user_id, tenant_id=other_user_id, category="semantic", content="Donnée privée B")
        session.add_all([mine, theirs])
        session.commit()
        mine_id, theirs_id = str(mine.id), str(theirs.id)

    listing = client.get("/api/v1/memory", headers=headers)
    assert listing.status_code == 200
    contents = [row["content"] for row in listing.json()]
    assert contents == ["Mon fournisseur préféré"]

    assert client.get("/api/v1/memory", headers=headers_other).json()[0]["content"] == "Donnée privée B"
    assert (
        client.patch(f"/api/v1/memory/{theirs_id}", json={"content": "piraté"}, headers=headers).status_code
        == 404
    )
    assert client.delete(f"/api/v1/memory/{theirs_id}", headers=headers).status_code == 404
    assert client.patch(f"/api/v1/memory/{mine_id}", json={"content": "à jour"}, headers=headers).status_code == 200


def test_memory_delete_and_filters(
    client: TestClient, headers: dict[str, str], user_id: uuid.UUID, db_session_factory
) -> None:
    with db_session_factory() as session:
        session.add_all(
            [
                Memory(user_id=user_id, tenant_id=user_id, category="episodic", content="Mission terminée hier"),
                Memory(user_id=user_id, tenant_id=user_id, category="semantic", content="Préférence horaire matin"),
            ]
        )
        session.commit()

    episodes = client.get("/api/v1/memory", params={"category": "episodic"}, headers=headers).json()
    assert len(episodes) == 1
    found = client.get("/api/v1/memory", params={"q": "horaire"}, headers=headers).json()
    assert len(found) == 1

    deleted = client.delete(f"/api/v1/memory/{episodes[0]['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/memory", headers=headers).status_code == 200
    assert len(client.get("/api/v1/memory", headers=headers).json()) == 1


def test_notifications_are_isolated(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
    wait_task,
) -> None:
    payload = client.post(
        "/api/v1/tasks", json={"goal": "Planifier un atelier"}, headers=headers
    ).json()
    wait_task(payload["id"])
    mine = client.get("/api/v1/notifications", headers=headers).json()
    assert mine and mine[0]["type"] == "task.completed"
    assert client.get("/api/v1/notifications", headers=headers_other).json() == []


def test_skills_catalogue_is_shared_but_read_only(
    client: TestClient, headers: dict[str, str], headers_other: dict[str, str]
) -> None:
    first = client.get("/api/v1/skills", headers=headers).json()
    second = client.get("/api/v1/skills", headers=headers_other).json()
    assert [s["name"] for s in first] == [s["name"] for s in second]
    assert client.post("/api/v1/skills", json={}, headers=headers).status_code == 405

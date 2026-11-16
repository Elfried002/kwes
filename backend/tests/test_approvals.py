"""Missions à approbation : création, approbation, refus, expiration, anti-replay."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db.models import Approval, Notification, TaskStep

PUBLISH_MESSAGE = "Publie le rapport de veille sur le marché des fintechs"


def _start_publish_mission(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/chat", json={"message": PUBLISH_MESSAGE, "mode": "mission"}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["task_id"]


def test_publish_mission_requires_approval(
    client: TestClient, headers: dict[str, str], wait_task, db_session_factory
) -> None:
    task_id = _start_publish_mission(client, headers)
    task = wait_task(task_id, statuses=("awaiting_approval",))
    assert task["status"] == "awaiting_approval"
    waiting = [s for s in task["steps"] if s["status"] == "awaiting_approval"]
    assert waiting and waiting[0]["declared_risk"] == "R1"

    approvals = client.get("/api/v1/approvals", headers=headers).json()
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval["status"] == "pending"
    assert approval["task_id"] == task_id
    assert len(approval["payload_hash"]) == 64
    assert approval["expires_at"]

    with db_session_factory() as session:
        notification = session.query(Notification).filter_by(user_id=uuid.UUID(approval["user_id"])).first()
        assert notification is not None


def test_approve_resumes_and_completes_mission(
    client: TestClient, headers: dict[str, str], wait_task, db_session_factory
) -> None:
    task_id = _start_publish_mission(client, headers)
    wait_task(task_id, statuses=("awaiting_approval",))
    approval = client.get("/api/v1/approvals", headers=headers).json()[0]

    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["approval"]["status"] == "approved"

    final = wait_task(task_id, statuses=("completed", "failed"))
    assert final["status"] == "completed", final
    assert final["progress"] == 100

    with db_session_factory() as session:
        row = session.get(Approval, uuid.UUID(approval["id"]))
        assert row is not None
        assert row.status == "consumed"

    # Anti-replay : une approbation déjà consommée ne peut pas être réutilisée.
    again = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=headers)
    assert again.status_code == 422


def test_reject_fails_mission(
    client: TestClient, headers: dict[str, str], wait_task, db_session_factory
) -> None:
    task_id = _start_publish_mission(client, headers)
    wait_task(task_id, statuses=("awaiting_approval",))
    approval = client.get("/api/v1/approvals", headers=headers).json()[0]

    response = client.post(f"/api/v1/approvals/{approval['id']}/reject", headers=headers)
    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "rejected"
    assert response.json()["task"]["status"] == "failed"

    final = wait_task(task_id, statuses=("failed",))
    assert final["error_code"] == "APPROVAL_REJECTED"

    with db_session_factory() as session:
        row = session.get(Approval, uuid.UUID(approval["id"]))
        assert row is not None and row.status == "rejected"


def test_expired_approval_cannot_be_used(
    client: TestClient, headers: dict[str, str], wait_task, db_session_factory
) -> None:
    task_id = _start_publish_mission(client, headers)
    wait_task(task_id, statuses=("awaiting_approval",))
    approval = client.get("/api/v1/approvals", headers=headers).json()[0]

    with db_session_factory() as session:
        row = session.get(Approval, uuid.UUID(approval["id"]))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.commit()

    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    with db_session_factory() as session:
        row = session.get(Approval, uuid.UUID(approval["id"]))
        assert row is not None and row.status == "expired"


def test_payload_change_invalidates_approval(
    client: TestClient, headers: dict[str, str], wait_task, db_session_factory
) -> None:
    task_id = _start_publish_mission(client, headers)
    task = wait_task(task_id, statuses=("awaiting_approval",))
    approval = client.get("/api/v1/approvals", headers=headers).json()[0]
    waiting = [s for s in task["steps"] if s["status"] == "awaiting_approval"][0]

    # La charge utile change après l'approbation -> hash différent -> refus.
    with db_session_factory() as session:
        step = session.get(TaskStep, uuid.UUID(waiting["id"]))
        assert step is not None
        payload = dict(step.input_json)
        payload["objective"] = "Autre objectif non approuvé"
        step.input_json = payload
        session.commit()

    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=headers)
    assert response.status_code == 422
    assert "charge utile" in response.json()["error"]["message"].lower()


def test_approval_of_other_user_is_hidden(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
    wait_task,
) -> None:
    task_id = _start_publish_mission(client, headers)
    wait_task(task_id, statuses=("awaiting_approval",))
    approval = client.get("/api/v1/approvals", headers=headers).json()[0]

    assert client.get("/api/v1/approvals", headers=headers_other).json() == []
    response = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=headers_other)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"

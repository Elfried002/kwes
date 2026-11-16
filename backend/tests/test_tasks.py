"""Missions : création, lecture, isolation, pause/reprise/annulation."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.db.models import Task


def test_create_task_completes_with_report(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"goal": "Structurer un plan de lancement pour une application de paiement"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["status"] in ("planning", "queued")
    assert task["steps"], task

    final = wait_task(task["id"])
    assert final["status"] == "completed", final
    assert final["progress"] == 100
    assert final["result_summary"]
    assert "MISSION" in final["result_summary"]
    assert final["started_at"] and final["completed_at"]


def test_create_task_with_explicit_steps(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={
            "goal": "Planifier le lancement d'un service",
            "steps": [
                {
                    "id": "step_1",
                    "skill": "business_planning",
                    "title": "Plan",
                    "input": {"objective": "Lancer un service de livraison"},
                    "risk": "R1",
                    "depends_on": [],
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["steps"][0]["skill"] == "business_planning"
    final = wait_task(task["id"])
    assert final["status"] == "completed"
    assert final["steps"][0]["output"]["kpis"]


def test_create_task_with_unknown_skill_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={
            "goal": "Faire quelque chose",
            "steps": [{"skill": "shell_exec", "input": {}}],
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_task_not_found(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_task_isolation_between_users(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
    create_mission,
) -> None:
    payload = create_mission("Prépare un plan de communication")
    other_list = client.get("/api/v1/tasks", headers=headers_other)
    assert other_list.status_code == 200
    assert other_list.json() == []

    assert client.get(f"/api/v1/tasks/{payload['task_id']}", headers=headers_other).status_code == 404
    assert (
        client.post(f"/api/v1/tasks/{payload['task_id']}/cancel", headers=headers_other).status_code
        == 404
    )


def test_pause_resume_and_cancel(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    payload = client.post(
        "/api/v1/chat",
        json={"message": "Publie le rapport de veille sur le marché", "mode": "mission"},
        headers=headers,
    ).json()
    task_id = payload["task_id"]
    waiting = wait_task(task_id, statuses=("awaiting_approval",))
    assert waiting["status"] == "awaiting_approval"

    paused = client.post(f"/api/v1/tasks/{task_id}/pause", headers=headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post(f"/api/v1/tasks/{task_id}/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"
    wait_task(task_id, statuses=("awaiting_approval",))

    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert all(step["status"] in ("completed", "skipped") for step in body["steps"])


def test_pause_invalid_state_rejected(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    payload = client.post(
        "/api/v1/tasks", json={"goal": "Plan marketing simple"}, headers=headers
    ).json()
    wait_task(payload["id"])
    response = client.post(f"/api/v1/tasks/{payload['id']}/pause", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_task_list_filters_status(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    payload = client.post(
        "/api/v1/tasks", json={"goal": "Planifier une campagne"}, headers=headers
    ).json()
    wait_task(payload["id"])
    completed = client.get("/api/v1/tasks", params={"status": "completed"}, headers=headers)
    assert completed.status_code == 200
    assert all(task["status"] == "completed" for task in completed.json())
    assert completed.headers["X-Total-Count"].isdigit()


def test_task_progress_is_persisted(
    client: TestClient, headers: dict[str, str], wait_task, db_session_factory
) -> None:
    payload = client.post(
        "/api/v1/tasks", json={"goal": "Élaborer une stratégie de croissance"}, headers=headers
    ).json()
    final = wait_task(payload["id"])
    with db_session_factory() as session:
        row = session.get(Task, uuid.UUID(payload["id"]))
        assert row is not None
        assert row.status == "completed"
        assert row.progress == 100
        assert row.result_summary == final["result_summary"]

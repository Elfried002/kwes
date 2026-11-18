"""Chat : réponse directe, mission, continuité de conversation, validations."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_direct_chat_creates_conversation_and_messages(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "Bonjour Kwes, comment vas-tu ?", "mode": "direct"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversation_id"] and body["message_id"]
    assert body["status"] == "completed"
    assert body["intent"] == "direct"
    assert "task_id" not in body
    assert body["response"].strip()

    messages = client.get(
        f"/api/v1/conversations/{body['conversation_id']}/messages", headers=headers
    ).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"].startswith("Bonjour Kwes")
    assert messages[1]["metadata"]["mock"] is True


def test_direct_chat_is_deterministic_in_mock_mode(
    client: TestClient, headers: dict[str, str]
) -> None:
    payload = {"message": "Peux-tu me rappeler la capitale du Bénin ?", "mode": "direct"}
    first = client.post("/api/v1/chat", json=payload, headers=headers).json()
    second = client.post("/api/v1/chat", json=payload, headers=headers).json()
    assert first["response"] == second["response"]


def test_mission_creates_task_with_steps(
    client: TestClient, headers: dict[str, str], wait_task, create_mission
) -> None:
    payload = create_mission("Prépare une étude de marché sur les fintechs au Bénin")
    assert payload["status"] in ("queued", "planning", "running", "awaiting_approval")
    task = wait_task(payload["task_id"])
    assert task["status"] == "completed", task
    assert task["progress"] == 100
    assert len(task["steps"]) >= 2
    assert [s["skill"] for s in task["steps"]][:2] == ["web_research", "business_planning"]
    for step in task["steps"]:
        assert step["status"] == "completed"
        assert step["output"]
        assert "_meta" not in step["input"]


def test_mission_reuses_existing_conversation(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    first = client.post(
        "/api/v1/chat", json={"message": "Bonjour", "mode": "direct"}, headers=headers
    ).json()
    second = client.post(
        "/api/v1/chat",
        json={
            "conversation_id": first["conversation_id"],
            "message": "Prépare un plan marketing pour une PME",
            "mode": "mission",
        },
        headers=headers,
    ).json()
    assert second["conversation_id"] == first["conversation_id"]
    wait_task(second["task_id"])
    messages = client.get(
        f"/api/v1/conversations/{first['conversation_id']}/messages", headers=headers
    ).json()
    assert len(messages) == 4


def test_cannot_write_into_other_user_conversation(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/conversations", json={"title": "Privée"}, headers=headers
    ).json()
    response = client.post(
        "/api/v1/chat",
        json={"conversation_id": created["id"], "message": "intrusion", "mode": "direct"},
        headers=headers_other,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_empty_message_is_validation_error(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/chat", json={"message": "", "mode": "direct"}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_too_long_message_is_validation_error(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/chat",
        json={"message": "a" * 9000, "mode": "direct"},
        headers=headers,
    )
    assert response.status_code == 422


def test_invalid_mode_rejected(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/chat", json={"message": "test", "mode": "turbo"}, headers=headers
    )
    assert response.status_code == 422


def test_mission_without_url_does_not_call_network(
    client: TestClient, headers: dict[str, str], wait_task, fake_fetcher
) -> None:
    payload = client.post(
        "/api/v1/chat",
        json={"message": "Structure un plan de lancement produit", "mode": "mission"},
        headers=headers,
    ).json()
    task = wait_task(payload["task_id"])
    assert task["status"] == "completed"
    assert fake_fetcher.calls == []


def test_llm_timeout_returns_retryable_503_not_500(
    client: TestClient, headers: dict[str, str], app
) -> None:
    """Un dépassement du fournisseur LLM est un 503 réessayable, pas un 500."""
    from app.agent.llm import LLMTimeout

    async def _timeout(*args, **kwargs):
        raise LLMTimeout()

    orchestrator = app.state.orchestrator
    original = orchestrator.handle_chat
    orchestrator.handle_chat = _timeout
    try:
        response = client.post(
            "/api/v1/chat",
            json={"message": "Cherche les actualités du solaire au Sénégal", "mode": "outil"},
            headers=headers,
        )
    finally:
        orchestrator.handle_chat = original

    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "PROVIDER_UNAVAILABLE"
    assert error["retryable"] is True
    assert "interne" not in error["message"].lower()


def test_chat_returns_mock_header(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/chat", json={"message": "Bonjour", "mode": "direct"}, headers=headers
    )
    assert response.headers.get("X-Kwes-Mock") == "1"

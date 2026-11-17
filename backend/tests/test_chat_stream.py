"""POST /chat/stream — streaming SSE réel (deltas, done, error) et persistance.

Le LLM est mocké : soit le client MOCK déterministe de l'application (clé
Gemini absente), soit un faux client injecté qui expose `stream_chat`.
Aucun appel réseau n'est effectué.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Sequence

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import LLMError
from app.api.chat import sse_frame


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """Analyse une réponse SSE texte en [(event, data), ...]."""
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = ""
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        name = event_name
        data_line = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_line = line[len("data:") :].strip()
        if data_line is None:
            continue
        events.append((name, json.loads(data_line)))
        event_name = ""
    return events


def stream_chat(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    with client.stream("POST", "/api/v1/chat/stream", json=payload, headers=headers) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())
    return raw, parse_sse(raw)


class FakeStreamingLLM:
    """Faux LLM : classifie en 'direct' et diffuse des fragments connus."""

    def __init__(self, chunks: Sequence[str] | None = None, *, fail_after: int | None = None) -> None:
        self.chunks = list(chunks or ["Bonjour, ", "je suis Kwes. ", "Comment puis-je aider ?"])
        self.fail_after = fail_after
        self.calls = 0

    async def chat(self, messages, **kwargs):  # pragma: no cover - utilisé pour la classification
        from app.agent.llm import LLMResult

        return LLMResult(content=json.dumps({"intent": "direct", "language": "fr"}), mock=True)

    async def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        max_tokens: int = 1200,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self.calls += 1
        for index, chunk in enumerate(self.chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise LLMError("panne simulée du fournisseur", retryable=True)
            yield chunk


def test_stream_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/chat/stream", json={"message": "Bonjour"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] in ("UNAUTHENTICATED", "UNAUTHORIZED")


def test_stream_emits_well_formed_events_with_mocked_llm(
    client: TestClient, headers: dict[str, str], app
) -> None:
    fake = FakeStreamingLLM()
    app.state.orchestrator.llm = fake

    raw, events = stream_chat(client, headers, {"message": "Bonjour Kwes", "mode": "direct"})

    assert raw.count("event: delta") == len(fake.chunks)
    assert events[0][0] == "delta"
    assert events[-1][0] == "done"
    deltas = [data["delta"] for name, data in events if name == "delta"]
    assert "".join(deltas) == "".join(fake.chunks)

    done = events[-1][1]
    assert done["status"] == "completed"
    assert done["intent"] == "direct"
    assert done["response"] == "".join(fake.chunks)
    assert done["conversation_id"] and done["message_id"]
    # Chaque delta porte l'identifiant de conversation (utile dès le 1er octet).
    assert all(data["conversation_id"] == done["conversation_id"] for _, data in events)
    assert fake.calls == 1


def test_stream_persists_user_and_assistant_messages(
    client: TestClient, headers: dict[str, str], app
) -> None:
    app.state.orchestrator.llm = FakeStreamingLLM(["Une réponse ", "persistée."])

    _, events = stream_chat(client, headers, {"message": "Message streamé", "mode": "direct"})
    done = events[-1][1]
    assert done["response"] == "Une réponse persistée."

    messages = client.get(
        f"/api/v1/conversations/{done['conversation_id']}/messages", headers=headers
    ).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Message streamé"
    assert messages[1]["content"] == done["response"]
    assert messages[1]["metadata"]["streamed"] is True


def test_stream_emits_error_event_when_llm_fails(
    client: TestClient, headers: dict[str, str], app
) -> None:
    app.state.orchestrator.llm = FakeStreamingLLM(["Début… ", "puis coupure"], fail_after=1)

    _, events = stream_chat(client, headers, {"message": "Test d'erreur", "mode": "direct"})

    names = [name for name, _ in events]
    assert names[0] == "delta"
    assert names[-1] == "error"
    error = events[-1][1]
    assert error["code"] == "PROVIDER_UNAVAILABLE"
    assert error["retryable"] is True
    assert "message" in error
    # Aucun `done` trompeur : rien n'est déclaré répondu.
    assert "done" not in names


def test_stream_continues_existing_conversation(
    client: TestClient, headers: dict[str, str], app
) -> None:
    app.state.orchestrator.llm = FakeStreamingLLM(["Premier tour."])
    _, first = stream_chat(client, headers, {"message": "Bonjour", "mode": "direct"})
    conversation_id = first[-1][1]["conversation_id"]

    app.state.orchestrator.llm = FakeStreamingLLM(["Second tour."])
    _, second = stream_chat(
        client,
        headers,
        {"message": "Encore", "conversation_id": conversation_id, "mode": "direct"},
    )
    assert second[-1][1]["conversation_id"] == conversation_id

    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=headers
    ).json()
    assert [m["content"] for m in messages] == ["Bonjour", "Premier tour.", "Encore", "Second tour."]


def test_stream_rejects_empty_message(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/chat/stream", json={"message": "   ", "mode": "direct"}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_stream_rejects_other_user_conversation(
    client: TestClient,
    headers: dict[str, str],
    headers_other: dict[str, str],
) -> None:
    created = client.post(
        "/api/v1/conversations", json={"title": "Privée"}, headers=headers
    ).json()
    response = client.post(
        "/api/v1/chat/stream",
        json={"conversation_id": created["id"], "message": "intrusion"},
        headers=headers_other,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_stream_mission_mode_creates_task(
    client: TestClient, headers: dict[str, str], wait_task
) -> None:
    _, events = stream_chat(
        client,
        headers,
        {"message": "Prépare une étude de marché sur les fintechs au Bénin", "mode": "mission"},
    )
    done = events[-1][1]
    assert done["intent"] == "mission"
    assert done["task_id"]
    task = wait_task(done["task_id"])
    assert task["status"] == "completed"


class RecordingEvents:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, user_id: Any, event: str, data: dict[str, Any]) -> None:
        self.published.append((event, data))


def test_stream_publishes_completed_without_duplicating_deltas(
    client: TestClient, headers: dict[str, str], app
) -> None:
    """Un seul canal par client : le SSE porte les deltas, le WS le `completed`."""
    recorder = RecordingEvents()
    app.state.orchestrator.events = recorder
    app.state.orchestrator.llm = FakeStreamingLLM(["Un ", "seul canal."])

    _, events = stream_chat(client, headers, {"message": "Test canal", "mode": "direct"})
    assert events[-1][0] == "done"

    names = [name for name, _ in recorder.published]
    assert "conversation.completed" in names
    assert "conversation.delta" not in names


def test_sse_frame_shape() -> None:
    frame = sse_frame("delta", {"delta": "a\nb", "conversation_id": None})
    assert frame.startswith("event: delta\ndata: ")
    assert frame.endswith("\n\n")
    # Le JSON tient sur une seule ligne, même avec des sauts de ligne dans le texte.
    assert frame.count("\n") == 3


@pytest.mark.parametrize("mode", ["direct", "auto"])
def test_stream_mock_mode_is_deterministic(
    client: TestClient, headers: dict[str, str], mode: str
) -> None:
    _, first = stream_chat(client, headers, {"message": "Explique ton fonctionnement", "mode": mode})
    _, second = stream_chat(client, headers, {"message": "Explique ton fonctionnement", "mode": mode})
    assert first[-1][1]["response"] == second[-1][1]["response"]
    assert len([n for n, _ in first if n == "delta"]) > 1

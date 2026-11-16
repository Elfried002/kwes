"""Outils conversationnels : exécution réelle, refus, mémoire, documents.

Ces tests utilisent un LLM scripté : ce n'est pas une simulation d'exécution,
c'est le modèle remplacé par un scénario déterministe pour prouver que la boucle
d'outils appelle réellement le registre, et que le refus est bien appliqué.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.deepseek import LLMResult
from app.agent.tools import CHAT_TOOL_NAMES, tool_definitions
from app.api.chat import sse_frame
from app.db.models import AuditLog, Document, Memory, Message


class ScriptedLLM:
    """LLM déterministe : rend les réponses fournies, dans l'ordre."""

    def __init__(self, replies: list[LLMResult]) -> None:
        self.replies = list(replies)
        self.seen: list[dict] = []

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.seen.append(
            {
                "messages": [dict(item) for item in messages],
                "tools": kwargs.get("tools"),
            }
        )
        if not self.replies:
            raise AssertionError("Le scénario LLM est épuisé : trop d'appels.")
        return self.replies.pop(0)


def _install(app, llm: ScriptedLLM) -> None:
    orchestrator = app.state.orchestrator
    orchestrator.llm = llm
    orchestrator.classifier.llm = llm
    orchestrator.planner.llm = llm
    orchestrator.tool_runner.llm = llm


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> LLMResult:
    return LLMResult(content="", tool_calls=[{"id": call_id, "name": name, "arguments": arguments}])


def test_tool_definitions_are_limited_to_conversational_skills(app) -> None:
    definitions = tool_definitions(app.state.registry)
    names = {item["function"]["name"] for item in definitions}
    assert names == set(CHAT_TOOL_NAMES)
    assert "business_planning" not in names
    for item in definitions:
        assert item["function"]["parameters"]["type"] == "object"
        assert "$schema" not in item["function"]["parameters"]


def test_outil_mode_executes_web_research_and_uses_its_result(
    client: TestClient, app, headers, db_session_factory
) -> None:
    llm = ScriptedLLM(
        [
            _tool_call("web_research", {"query": "paiements mobiles Afrique de l'Ouest", "depth": "quick"}),
            LLMResult(content="Les paiements mobiles progressent de 18 % par an selon la source citée."),
        ]
    )
    _install(app, llm)

    r = client.post(
        "/api/v1/chat",
        json={"message": "Cherche les chiffres des paiements mobiles", "mode": "outil"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "18 %" in body["response"]
    assert body["intent"] == "direct"

    # L'outil a bien été proposé au modèle, puis exécuté.
    assert [tool["function"]["name"] for tool in llm.seen[0]["tools"]] == list(CHAT_TOOL_NAMES)
    with db_session_factory() as session:
        message = session.get(Message, __import__("uuid").UUID(body["message_id"]))
        assert message is not None
        assert message.meta["tools"][0]["name"] == "web_research"
        assert message.meta["tools"][0]["status"] == "executed"
        audits = session.query(AuditLog).filter(AuditLog.action == "chat.tool.call").all()
        assert audits and audits[0].decision == "allow"


def test_tool_outside_chat_allowlist_is_refused(
    client: TestClient, app, headers
) -> None:
    llm = ScriptedLLM(
        [
            _tool_call("business_planning", {"objective": "préparer un plan"}),
            LLMResult(content="Je ne peux pas exécuter cette action ici."),
        ]
    )
    _install(app, llm)

    r = client.post(
        "/api/v1/chat",
        json={"message": "Structure un plan", "mode": "outil"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    tool_messages = [
        item for item in llm.seen[1]["messages"] if item.get("role") == "tool"
    ]
    assert tool_messages, "le refus doit être renvoyé au modèle comme résultat d'outil"
    assert json.loads(tool_messages[0]["content"])["status"] == "refused"


def test_remember_writes_memory_and_next_turn_injects_it(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    fact = "Préfère travailler le matin et recevoir des réponses courtes."
    llm = ScriptedLLM(
        [
            _tool_call("remember", {"fact": fact, "category": "semantic"}),
            LLMResult(content="C'est noté."),
            LLMResult(content="Voici une réponse courte."),
        ]
    )
    _install(app, llm)

    first = client.post(
        "/api/v1/chat",
        json={"message": "Retiens que je préfère travailler le matin", "mode": "outil"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    with db_session_factory() as session:
        memories = session.query(Memory).filter(Memory.user_id == user_id).all()
        assert [row.content for row in memories] == [fact]

    second = client.post(
        "/api/v1/chat",
        json={
            "message": "Comment vas-tu organiser ma journée ?",
            "mode": "direct",
            "conversation_id": conversation_id,
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    system_prompt = llm.seen[-1]["messages"][0]["content"]
    assert fact in system_prompt


def test_remember_updates_instead_of_duplicating(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    fact = "Travaille sur Kwes en priorité."
    llm = ScriptedLLM(
        [
            _tool_call("remember", {"fact": fact}),
            LLMResult(content="Noté."),
            _tool_call("remember", {"fact": "  " + fact.upper() + "  "}),
            LLMResult(content="Toujours noté."),
        ]
    )
    _install(app, llm)

    for message in ("Retiens que je travaille sur Kwes", "Retiens encore Kwes en priorité"):
        r = client.post(
            "/api/v1/chat", json={"message": message, "mode": "outil"}, headers=headers
        )
        assert r.status_code == 200, r.text

    with db_session_factory() as session:
        rows = session.query(Memory).filter(Memory.user_id == user_id).all()
        assert len(rows) == 1


def test_document_write_creates_downloadable_private_document(
    client: TestClient, app, headers, headers_other, db_session_factory
) -> None:
    llm = ScriptedLLM(
        [
            _tool_call(
                "document_write",
                {
                    "title": "Note sur les paiements mobiles",
                    "content": "# Note\n\nLes paiements mobiles progressent de 18 % par an.",
                    "format": "markdown",
                },
            ),
            LLMResult(content="Le document est prêt."),
        ]
    )
    _install(app, llm)

    r = client.post(
        "/api/v1/chat",
        json={"message": "Rédige une note sur les paiements mobiles", "mode": "outil"},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    listing = client.get("/api/v1/documents", headers=headers)
    assert listing.status_code == 200
    documents = listing.json()
    assert len(documents) == 1
    assert documents[0]["title"] == "Note sur les paiements mobiles"

    document_id = documents[0]["id"]
    detail = client.get(f"/api/v1/documents/{document_id}", headers=headers)
    assert detail.status_code == 200
    assert "18 %" in detail.json()["content"]

    download = client.get(f"/api/v1/documents/{document_id}/download", headers=headers)
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    # Isolation : un autre utilisateur n'y accède pas, et ne le voit pas.
    assert client.get(f"/api/v1/documents/{document_id}", headers=headers_other).status_code == 404
    assert client.get("/api/v1/documents", headers=headers_other).json() == []

    with db_session_factory() as session:
        assert session.query(Document).count() == 1


def test_stream_with_tools_emits_deltas_and_reports_tools(
    client: TestClient, app, headers
) -> None:
    llm = ScriptedLLM(
        [
            _tool_call("document_write", {"title": "Compte rendu", "content": "Ligne un.\nLigne deux."}),
            LLMResult(content="Le compte rendu est enregistré et prêt à être ouvert."),
        ]
    )
    _install(app, llm)

    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "Rédige un compte rendu", "mode": "outil"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        raw = "".join(response.iter_text())

    events: list[tuple[str, dict]] = []
    name = ""
    for block in raw.split("\n\n"):
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if data is not None:
            events.append((name, data))
            name = ""

    deltas = "".join(payload["delta"] for event, payload in events if event == "delta")
    assert "compte rendu est enregistré" in deltas
    done = [payload for event, payload in events if event == "done"][0]
    assert done["intent"] == "direct"
    assert done["tools"][0]["name"] == "document_write"
    assert done["tools"][0]["status"] == "executed"


def test_tool_loop_is_bounded(client: TestClient, app, headers, settings) -> None:
    # Quatre appels sont disponibles dans le scénario : la boucle doit s'arrêter
    # après `max_tool_rounds` et produire une réponse finale sans outils.
    calls = [
        _tool_call("remember", {"fact": f"Fait numéro {index}"}, call_id=f"call_{index}")
        for index in range(1, 5)
    ]
    llm = ScriptedLLM(calls[:2] + [LLMResult(content="Réponse finale après outils.")])
    _install(app, llm)

    r = client.post(
        "/api/v1/chat",
        json={"message": "Retiens plusieurs choses", "mode": "outil"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["response"] == "Réponse finale après outils."
    # 2 tours d'outils + 1 appel final sans outils.
    assert len(llm.seen) == settings.max_tool_rounds + 1
    assert llm.seen[-1]["tools"] is None

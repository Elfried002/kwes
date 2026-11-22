"""Découverte du premier contact et apprentissage progressif.

Deux familles de preuves :

* la **détection** est une fonction pure (`app.agent.discovery`) : elle se teste
  sans base ni modèle, sur des cas limites explicites ;
* le **comportement réel** est vérifié de bout en bout par l'API (`/chat`) avec
  un LLM scripté : on lit ce que le prompt contient réellement et ce qui est
  écrit en base, pas ce que le code prétend faire.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent import discovery
from app.agent.llm import LLMResult
from app.agent.memory_facts import extract_facts
from app.core.utils import utcnow
from app.db.models import Memory, UserOnboarding


class ScriptedLLM:
    def __init__(self, replies: list[LLMResult]) -> None:
        self.replies = list(replies)
        self.seen: list[dict] = []

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.seen.append({"messages": [dict(item) for item in messages]})
        if not self.replies:
            raise AssertionError("Scénario LLM épuisé : trop d'appels.")
        return self.replies.pop(0)


def _install(app, llm: ScriptedLLM) -> None:
    orchestrator = app.state.orchestrator
    orchestrator.llm = llm
    orchestrator.classifier.llm = llm
    orchestrator.planner.llm = llm
    orchestrator.tool_runner.llm = llm


def _replies(count: int, prefix: str = "Réponse") -> list[LLMResult]:
    return [LLMResult(content=f"{prefix} {index}.") for index in range(1, count + 1)]


def _posts(client: TestClient, headers: dict[str, str], message: str, conversation_id: str | None = None) -> dict:
    payload: dict = {"message": message, "mode": "direct"}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    response = client.post("/api/v1/chat", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _messages(client: TestClient, headers: dict[str, str], conversation_id: str) -> list[dict]:
    response = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Détection (fonction pure)
# ---------------------------------------------------------------------------
def test_first_contact_detected_without_facts_and_short_history() -> None:
    assert discovery.is_first_contact(
        fact_count=0, conversation_messages=1, onboarding=None
    )
    assert discovery.is_first_contact(
        fact_count=0, conversation_messages=4, onboarding=None
    )


def test_no_discovery_once_facts_exist() -> None:
    assert not discovery.is_first_contact(
        fact_count=1, conversation_messages=1, onboarding=None
    )


def test_no_discovery_when_conversation_is_already_engaged() -> None:
    assert not discovery.is_first_contact(
        fact_count=0, conversation_messages=5, onboarding=None
    )


def test_discovery_never_replays_after_completion() -> None:
    row = UserOnboarding(user_id=uuid.uuid4(), step=3, completed_at=utcnow())
    assert not discovery.is_first_contact(
        fact_count=0, conversation_messages=1, onboarding=row
    )


def test_unfinished_sequence_resumes_even_in_a_new_conversation() -> None:
    row = UserOnboarding(user_id=uuid.uuid4(), step=2, completed_at=None)
    assert discovery.is_first_contact(
        fact_count=0, conversation_messages=1, onboarding=row
    )


def test_questions_follow_the_agreed_order() -> None:
    assert [discovery.question_for(step) for step in range(4)] == [
        "nom",
        "activite",
        "priorite",
        None,
    ]
    assert discovery.MAX_QUESTIONS == 3


def test_answered_topics_are_not_asked_again() -> None:
    assert discovery.advance_for_answers(0, {"nom"}) == 1
    assert discovery.advance_for_answers(0, {"nom", "activite"}) == 2
    assert discovery.advance_for_answers(2, set()) == 2
    assert discovery.advance_for_answers(0, {"priorite"}) == 0


def test_prompt_block_asks_one_question_and_closes() -> None:
    opening = discovery.prompt_block(
        discovery.DiscoveryPlan(active=True, step=0, question_key="nom", closing=False)
    )
    assert "Comment souhaitez-vous que je vous appelle ?" in opening
    assert "une seule question" in opening
    closing = discovery.prompt_block(
        discovery.DiscoveryPlan(active=True, step=3, question_key=None, closing=True)
    )
    assert "ne pose plus AUCUNE question" in closing


# ---------------------------------------------------------------------------
# Séquence réelle par l'API
# ---------------------------------------------------------------------------
def test_first_conversation_runs_three_questions_then_a_summary(
    client: TestClient, app, settings, headers, user_id, db_session_factory
) -> None:
    llm = ScriptedLLM(_replies(6))
    _install(app, llm)

    first = _posts(client, headers, "Bonjour")
    conversation_id = first["conversation_id"]

    messages = _messages(client, headers, conversation_id)
    assert messages[-1]["metadata"]["discovery"] == {
        "active": True,
        "step": 0,
        "question": "nom",
        "closing": False,
    }
    prompt = llm.seen[0]["messages"][0]["content"]
    assert "PHASE DE DÉCOUVERTE" in prompt
    assert "Comment souhaitez-vous que je vous appelle ?" in prompt

    _posts(client, headers, "Awa", conversation_id)
    assert "Qu'est-ce que vous faites" in llm.seen[1]["messages"][0]["content"]

    _posts(client, headers, "Je travaille dans l'agroalimentaire", conversation_id)
    assert "Qu'attendez-vous de moi en priorité ?" in llm.seen[2]["messages"][0]["content"]

    _posts(client, headers, "Merci", conversation_id)
    closing_prompt = llm.seen[3]["messages"][0]["content"]
    assert "Dernier tour : ne pose plus AUCUNE question" in closing_prompt

    with db_session_factory() as session:
        row = session.get(UserOnboarding, user_id)
        assert row is not None
        assert row.step == 3
        assert row.completed_at is not None
        assert row.tenant_id == user_id

    # Une conversation suivante ne rejoue jamais la découverte.
    later = _posts(client, headers, "Tu te souviens de moi ?")
    later_messages = _messages(client, headers, later["conversation_id"])
    assert "discovery" not in later_messages[-1]["metadata"]
    assert "PHASE DE DÉCOUVERTE" not in llm.seen[-1]["messages"][0]["content"]


def test_discovery_is_skipped_when_a_fact_already_exists(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    with db_session_factory() as session:
        session.add(
            Memory(
                user_id=user_id,
                tenant_id=user_id,
                category="semantic",
                content="Activité : import-export",
                source_type="agent",
            )
        )
        session.commit()

    llm = ScriptedLLM(_replies(2))
    _install(app, llm)
    body = _posts(client, headers, "Bonjour")
    messages = _messages(client, headers, body["conversation_id"])
    assert "discovery" not in messages[-1]["metadata"]
    assert "PHASE DE DÉCOUVERTE" not in llm.seen[0]["messages"][0]["content"]


def test_first_turn_extracts_the_name_without_asking(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    """Une personne qui se présente d'emblée n'est pas interrogée deux fois."""
    llm = ScriptedLLM(_replies(3))
    _install(app, llm)
    body = _posts(client, headers, "Bonjour, je m'appelle Awa")
    prompt = llm.seen[0]["messages"][0]["content"]
    assert "Comment souhaitez-vous que je vous appelle ?" not in prompt
    assert "Qu'est-ce que vous faites" in prompt

    with db_session_factory() as session:
        row = session.get(UserOnboarding, user_id)
        assert row is not None and row.step >= 1
        contents = [m.content for m in session.query(Memory).filter(Memory.user_id == user_id)]
        assert "Prénom : Awa" in contents


# ---------------------------------------------------------------------------
# Apprentissage, déduplication, scoping
# ---------------------------------------------------------------------------
def test_facts_are_learned_and_reused_without_being_asked_again(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    llm = ScriptedLLM(_replies(4))
    _install(app, llm)

    first = _posts(client, headers, "Je m'appelle Awa et je dirige une boutique de cosmétiques à Cotonou")

    with db_session_factory() as session:
        rows = session.query(Memory).filter(Memory.user_id == user_id).all()
        contents = {row.content for row in rows}
        assert "Prénom : Awa" in contents
        assert any(content.startswith("Activité : ") for content in contents)
        for row in rows:
            assert row.tenant_id == user_id, "une mémoire doit être rattachée au tenant de son auteur"
            assert row.source_type == "agent"

    # Clôture de la découverte (sa dernière question portait sur la priorité).
    second = _posts(
        client, headers, "Surtout des synthèses courtes", first["conversation_id"]
    )
    assert "Dernier tour" in llm.seen[-1]["messages"][0]["content"]

    # Conversation suivante : le fait est dans le prompt, sans être redemandé.
    third = _posts(client, headers, "Qu'est-ce que tu peux faire pour moi ?")
    prompt = llm.seen[-1]["messages"][0]["content"]
    assert "Prénom : Awa" in prompt
    assert "boutique de cosmétiques" in prompt
    assert "Comment souhaitez-vous que je vous appelle ?" not in prompt
    later = _messages(client, headers, third["conversation_id"])
    assert "discovery" not in later[-1]["metadata"]


def test_same_fact_is_updated_not_duplicated(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    llm = ScriptedLLM(_replies(4))
    _install(app, llm)

    _posts(client, headers, "Je travaille chez Acme")
    _posts(client, headers, "Je travaille chez Acme SA")

    with db_session_factory() as session:
        rows = [
            row
            for row in session.query(Memory).filter(Memory.user_id == user_id).all()
            if row.content.startswith("Activité : ")
        ]
        assert len(rows) == 1
        assert rows[0].content == "Activité : Acme SA"


def test_repeating_the_same_message_creates_one_memory(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    llm = ScriptedLLM(_replies(4))
    _install(app, llm)
    _posts(client, headers, "Je préfère les réponses courtes")
    _posts(client, headers, "Je préfère les réponses courtes")

    with db_session_factory() as session:
        rows = session.query(Memory).filter(Memory.user_id == user_id).all()
        assert len(rows) == 1


def test_memory_never_leaks_to_another_user_of_the_same_tenant(
    client: TestClient, app, headers, user_id, other_user_id, db_session_factory
) -> None:
    with db_session_factory() as session:
        session.add(
            Memory(
                user_id=other_user_id,
                tenant_id=user_id,  # même espace de travail que l'utilisateur courant
                category="semantic",
                content="Prénom : Confidentiel",
                source_type="agent",
            )
        )
        session.commit()

    llm = ScriptedLLM(_replies(2))
    _install(app, llm)
    _posts(client, headers, "Bonjour")
    prompt = llm.seen[0]["messages"][0]["content"]
    assert "Confidentiel" not in prompt

    with db_session_factory() as session:
        own = session.query(Memory).filter(Memory.user_id == user_id).all()
        assert own == []


def test_sensitive_data_is_never_stored(
    client: TestClient, app, headers, user_id, db_session_factory
) -> None:
    llm = ScriptedLLM(_replies(4))
    _install(app, llm)
    _posts(client, headers, "Mon mot de passe est Kwes2026! et je préfère le café")
    _posts(client, headers, "Ma carte 4111 1111 1111 1111 doit rester secrète")

    with db_session_factory() as session:
        assert session.query(Memory).filter(Memory.user_id == user_id).all() == []

    assert extract_facts("Mon mot de passe est Kwes2026!") == []
    assert extract_facts("Voici ma clé api_key: sk-abcdefghijklmnop") == []
    assert extract_facts("Je m'appelle Awa") != []


def test_autolearn_can_be_disabled(settings) -> None:
    assert settings.memory_autolearn is True

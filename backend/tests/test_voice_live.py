"""Réglage de la voix : tour de parole, langue et tickets multi-workers.

Ces tests portent sur des régressions mesurées en production, pas sur des
intentions :

- 9 ouvertures de session sur 12 refusées en 403 parce que les tickets vivaient
  dans la mémoire d'un seul worker (``--workers 2``) ;
- un ticket sans langue laissait une session neuve sans consigne de langue ;
- un ``thinking_config`` inutile sur le modèle vocal ajoutait une délibération
  avant la première syllabe ;
- une trame audio hors prise de parole rouvrait un micro-tour (répétitions,
  « ¿Qué? », fermeture de session en 1007).
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.agent.gemini_live import SYSTEM_PROMPT, Usage, build_config
from app.api import voice_live

BACKEND_DIR = Path(__file__).resolve().parents[1]


# -- Configuration de la session Live ---------------------------------------


def test_voice_config_carries_no_thinking(settings) -> None:
    """Le raisonnement approfondi n'a rien à faire sur la voix."""
    config = build_config(settings, language="fr")
    assert getattr(config, "thinking_config", None) is None
    # La possibilité a été retirée du constructeur : plus aucun chemin ne peut
    # réactiver ThinkingConfig par inadvertance sur la session vocale.
    assert "thinking_level" not in inspect.signature(build_config).parameters


def _prompt(settings, language: str | None = None) -> str:
    """Consigne système, espaces normalisés (le prompt est replié sur 90 colonnes)."""
    raw = build_config(settings, language=language).system_instruction.parts[0].text
    return " ".join(raw.split())


def test_voice_prompt_locks_the_language(settings) -> None:
    text = _prompt(settings)
    assert "espagnol" in text
    assert "¿Qué?" in text
    assert "Je n'ai pas compris" in text
    # Un ticket sans langue tombe sur le français, jamais sur l'absence de règle.
    assert "français" in text


def test_voice_prompt_forbids_repetition(settings) -> None:
    text = _prompt(settings, "fr")
    assert "Tenue de parole" in text
    assert "une seule réponse par tour" in text
    assert "tu ne redis jamais une phrase déjà" in text
    # Le prompt ne doit jamais autoriser le changement de langue spontané.
    assert "sans qu'on te le demande" not in text


def test_prompt_template_keeps_its_placeholders() -> None:
    # Un placeholder oublié fait échouer `format` au premier appel réel.
    rendered = SYSTEM_PROMPT.format(pronunciation="p", now="n", memory_block="")
    assert "{" not in rendered


# -- Trames audio hors prise de parole --------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_realtime_input(self, **kwargs) -> None:
        self.calls.append(kwargs)


async def test_audio_outside_a_turn_is_dropped(settings) -> None:
    """Une trame hors `activity_start` produisait un micro-tour et un 1007."""
    from app.agent.gemini_live import GeminiLiveSession

    live = GeminiLiveSession(settings, client=object())
    live._session = _FakeSession()  # noqa: SLF001 — session simulée
    await live.send_audio(b"\x00\x00" * 1600)
    assert live._session.calls == []
    assert live.usage.dropped_frames == 1

    await live.activity_start()
    await live.send_audio(b"\x00\x00" * 1600)
    assert len(live._session.calls) == 2
    assert live.usage.dropped_frames == 1


async def test_activity_markers_are_paired(settings) -> None:
    import asyncio

    from app.agent.gemini_live import GeminiLiveSession

    live = GeminiLiveSession(settings, client=object())
    live._session = _FakeSession()  # noqa: SLF001
    await live.activity_end()  # sans start : ignoré
    assert live._session.calls == []
    await live.activity_start()
    await live.activity_start()  # idempotent
    await live.activity_end()
    await live.activity_end()  # sans start : ignoré
    # Tour de quelques millisecondes : la fin est retenue (anti-micro-tour).
    assert [list(call)[0] for call in live._session.calls] == ["activity_start"]
    await asyncio.sleep(0.3)
    assert [list(call)[0] for call in live._session.calls] == ["activity_start", "activity_end"]


async def test_a_short_turn_merges_into_the_next_one(settings) -> None:
    """La queue de phrase ne produit pas une réponse à un mot."""
    from app.agent.gemini_live import GeminiLiveSession

    live = GeminiLiveSession(settings, client=object())
    live._session = _FakeSession()  # noqa: SLF001
    await live.activity_start()
    await live.activity_end()  # trop court : fin retenue
    assert live.usage.short_turns == 1
    # L'utilisateur continue de parler : la fin retenue est annulée.
    await live.send_audio(b"\x00\x00" * 1600)
    kinds = [list(call)[0] for call in live._session.calls]
    assert "activity_end" not in kinds
    assert "audio" in kinds


def test_usage_exposes_dropped_frames() -> None:
    assert "dropped_frames" in Usage(started_at=0.0).as_dict()


# -- Tickets ----------------------------------------------------------------


def test_ticket_defaults_to_french(client, headers) -> None:
    response = client.post("/api/v1/voice/ticket", headers=headers, json={})
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "fr"
    assert "." in body["ticket"]  # signé, plus une simple clé en mémoire


def test_ticket_without_body_defaults_to_french(client, headers) -> None:
    response = client.post("/api/v1/voice/ticket", headers=headers)
    assert response.status_code == 200
    assert response.json()["language"] == "fr"


def test_ticket_unknown_language_falls_back_to_french(client, headers) -> None:
    response = client.post("/api/v1/voice/ticket", headers=headers, json={"language": "xx"})
    assert response.status_code == 200
    assert response.json()["language"] == "fr"


def test_ticket_keeps_a_supported_language(client, headers) -> None:
    response = client.post("/api/v1/voice/ticket", headers=headers, json={"language": "en"})
    assert response.json()["language"] == "en"


def test_ticket_is_single_use(settings, user_id) -> None:
    ticket = voice_live._issue_ticket(user_id, "fr", settings=settings)
    first = voice_live._consume_ticket(ticket, settings=settings)
    assert first is not None
    assert first[0] == user_id
    assert first[1] == "fr"
    assert voice_live._consume_ticket(ticket, settings=settings) is None


def test_ticket_is_rejected_when_tampered(settings, user_id) -> None:
    ticket = voice_live._issue_ticket(user_id, "fr", settings=settings)
    body, signature = ticket.split(".", 1)
    assert voice_live._consume_ticket(f"{body}.{signature[:-1]}0", settings=settings) is None
    assert voice_live._consume_ticket("n-importe-quoi", settings=settings) is None


def test_ticket_survives_a_restart_and_another_worker(settings, user_id) -> None:
    """La validité ne dépend pas de la mémoire du processus qui l'a émis.

    Deux workers uvicorn ne partagent pas leur mémoire : c'est exactement ce qui
    faisait échouer 9 ouvertures sur 12. Le ticket est vérifié dans un processus
    neuf, qui n'a jamais vu ni le ticket ni le nonce.
    """
    ticket = voice_live._issue_ticket(user_id, "fr", settings=settings)
    script = (
        "import json, sys\n"
        "from app.api.voice_live import _consume_ticket\n"
        "from app.core.config import Settings\n"
        "consumed = _consume_ticket(sys.argv[1], settings=Settings(app_env='test'))\n"
        "print(json.dumps([str(consumed[0]), consumed[1]] if consumed else None))\n"
    )
    outcome = subprocess.run(
        [sys.executable, "-c", script, ticket],
        cwd="/tmp",
        env={"PYTHONPATH": str(BACKEND_DIR), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert outcome.returncode == 0, outcome.stderr[-400:]
    assert json.loads(outcome.stdout.strip()) == [str(user_id), "fr"]


def test_expired_ticket_is_refused(settings, user_id, monkeypatch) -> None:
    ticket = voice_live._issue_ticket(user_id, "fr", settings=settings)
    real_time = voice_live.time.time
    monkeypatch.setattr(voice_live.time, "time", lambda: real_time() + voice_live.TICKET_TTL_SECONDS + 1)
    assert voice_live._consume_ticket(ticket, settings=settings) is None


def test_websocket_rejects_a_missing_ticket(client, headers, settings) -> None:
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/voice/live") as socket:
            socket.receive_json()


def test_issued_user_id_is_a_uuid(settings) -> None:
    uid = uuid.uuid4()
    ticket = voice_live._issue_ticket(uid, None, settings=settings)
    consumed = voice_live._consume_ticket(ticket, settings=settings)
    assert consumed is not None
    assert isinstance(consumed[0], uuid.UUID)
    assert consumed[1] == "fr"  # sans langue : français

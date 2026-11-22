"""Flux de texte : le modèle texte, jamais une session Live.

Régression observée en production le 22/11 : `/chat/stream` répondait
systématiquement « service indisponible » parce que le flux ouvrait une session
Live (`bidiGenerateContent`) avec le modèle texte
(`1008 … is not supported for bidiGenerateContent`). Une session Live est
réservée à l'audio ; le texte doit passer par `generate_content_stream`.
"""

from __future__ import annotations

import pytest

from app.agent.live_reasoner import LiveReasoner
from app.core.config import Settings


class _FakeStream:
    def __init__(self, fragments: list[str]) -> None:
        self.fragments = fragments

    def __aiter__(self):
        async def _gen():
            for fragment in self.fragments:
                yield type("Chunk", (), {"text": fragment})()

        return _gen()


class _FakeModels:
    def __init__(self, fragments: list[str]) -> None:
        self.fragments = fragments
        self.calls: list[dict] = []

    async def generate_content_stream(self, *, model, contents, config):  # noqa: ANN001
        self.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeStream(self.fragments)


class _FakeClient:
    def __init__(self, fragments: list[str]) -> None:
        self.aio = type("Aio", (), {"models": _FakeModels(fragments)})()


async def test_text_stream_uses_the_text_model(settings: Settings) -> None:
    reasoner = LiveReasoner(settings)
    fake = _FakeClient(["Bon", "jour"])
    reasoner._client = fake  # noqa: SLF001 — injection du SDK pour le test

    chunks = [
        chunk
        async for chunk in reasoner.stream(
            [{"role": "system", "content": "Tu es Kwes."}, {"role": "user", "content": "Bonjour"}]
        )
    ]

    assert chunks == ["Bon", "jour"]
    assert fake.aio.models.calls[0]["model"] == settings.google_text_model
    assert fake.aio.models.calls[0]["model"] != settings.google_live_model
    assert not hasattr(fake, "live")  # aucune session Live ouverte


async def test_text_stream_sends_the_system_prompt_and_history(settings: Settings) -> None:
    reasoner = LiveReasoner(settings)
    fake = _FakeClient(["ok"])
    reasoner._client = fake  # noqa: SLF001

    chunks = [
        chunk
        async for chunk in reasoner.stream(
            [
                {"role": "system", "content": "Consigne de test."},
                {"role": "user", "content": "Bonjour"},
                {"role": "assistant", "content": "Salut"},
                {"role": "user", "content": "Ça va ?"},
            ]
        )
    ]
    assert chunks == ["ok"]
    call = fake.aio.models.calls[0]
    assert call["config"].system_instruction == "Consigne de test."
    roles = [content.role for content in call["contents"]]
    assert roles == ["user", "model", "user"]

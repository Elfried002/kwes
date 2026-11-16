"""Route /voice/voices : catalogue des voix, cache court, aucune clé exposée."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.voice import ElevenLabsVoiceProvider, _parse_voice
from app.core.config import Settings

CATALOG = {
    "voices": [
        {
            "voice_id": "JBFqnCBsd6RMkjVDRZzb",
            "name": "George - Warm, Captivating Storyteller",
            "description": "Un conteur chaleureux.",
            "preview_url": "https://example.invalid/george.mp3",
            "labels": {
                "accent": "british",
                "gender": "male",
                "use_case": "conversational",
                "language": "en",
                "descriptive": "warm",
            },
        },
        {
            "voice_id": "EXAVITQu4vr4xnSDxMaL",
            "name": "Sarah",
            "labels": {"accent": "american", "gender": "female", "language": "en"},
            "verified_languages": [{"language": "fr", "accent": "parisien"}],
        },
        {"name": "Sans identifiant"},
    ]
}


def _real_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"elevenlabs_api_key": "cle-de-test", "elevenlabs_voice_id": "v-defaut"})


def test_voices_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/voice/voices")
    assert response.status_code == 401


def test_voices_in_mock_mode_are_empty(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/api/v1/voice/voices", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["voices"] == []
    assert body["mock"] is True
    assert body["default_voice_id"] is None
    assert body["reason"]


async def test_list_voices_parses_catalog_and_caches(settings: Settings) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        assert request.url.path.endswith("/v1/voices")
        assert request.headers.get("xi-api-key") == "cle-de-test"
        return httpx.Response(200, json=CATALOG)

    provider = ElevenLabsVoiceProvider(
        _real_settings(settings), transport=httpx.MockTransport(handler)
    )

    first = await provider.list_voices()
    assert first.mock is False
    assert first.cached is False
    assert [voice.id for voice in first.voices] == [
        "JBFqnCBsd6RMkjVDRZzb",
        "EXAVITQu4vr4xnSDxMaL",
    ]
    george = first.voices[0]
    assert george.name == "George"
    assert george.gender == "male"
    assert george.language == "en"
    assert george.accent == "british"
    assert george.description == "warm"
    # Aucune clé fournisseur dans ce que l'API renverra.
    assert "cle-de-test" not in str(george.as_dict())

    # Langue déduite de `verified_languages` quand les labels n'en donnent pas.
    assert first.voices[1].language == "en"
    assert first.voices[1].description is None

    second = await provider.list_voices()
    assert second.cached is True
    assert len(second.voices) == 2
    assert calls["count"] == 1  # cache court : un seul appel fournisseur


async def test_list_voices_failure_is_reported_without_raising(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    provider = ElevenLabsVoiceProvider(
        _real_settings(settings), transport=httpx.MockTransport(handler)
    )
    result = await provider.list_voices()
    assert result.voices == []
    assert result.reason == "Catalogue des voix indisponible pour le moment."


async def test_list_voices_keeps_last_catalog_when_refresh_fails(settings: Settings) -> None:
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json=CATALOG)

    provider = ElevenLabsVoiceProvider(
        _real_settings(settings), transport=httpx.MockTransport(handler)
    )
    await provider.list_voices()
    state["fail"] = True
    refreshed = await provider.list_voices(force=True)
    assert len(refreshed.voices) == 2
    assert refreshed.reason == "Catalogue des voix indisponible pour le moment."


async def test_list_voices_network_error_is_normalised(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("réseau coupé", request=request)

    provider = ElevenLabsVoiceProvider(
        _real_settings(settings), transport=httpx.MockTransport(handler)
    )
    result = await provider.list_voices()
    assert result.voices == []
    assert result.reason


def test_parse_voice_ignores_entries_without_id() -> None:
    assert _parse_voice({"name": "Fantôme"}) is None
    assert _parse_voice({"voice_id": ""}) is None


def test_synthesize_rejects_a_voice_id_that_is_not_an_id(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/voice/synthesize",
        json={"text": "Bonjour", "voice_id": "../../admin"},
        headers=headers,
    )
    assert response.status_code in (400, 422)


@pytest.mark.parametrize("voice_id", ["abc123", "JBFqnCBsd6RMkjVDRZzb", "v-defaut"])
def test_synthesize_accepts_a_plain_voice_id(
    client: TestClient, headers: dict[str, str], voice_id: str
) -> None:
    response = client.post(
        "/api/v1/voice/synthesize",
        json={"text": "Bonjour", "voice_id": voice_id},
        headers=headers,
    )
    assert response.status_code == 200

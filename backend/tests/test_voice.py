"""Voix Gemini : catalogue figé, synthèse ponctuelle, aucun secret exposé."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.agent.voice import GeminiVoiceProvider, VOICE_CATALOGUE, build_voice_provider, pcm_to_wav
from app.core.config import Settings


def test_voices_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/voice/voices").status_code == 401


def test_voices_catalogue_is_served_without_network(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/api/v1/voice/voices", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["voices"]] == [name for name, _, _ in VOICE_CATALOGUE]
    assert body["mock"] is True  # aucun fournisseur configuré dans les tests
    assert body["default_voice_id"] is None


def test_synthesize_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/v1/voice/synthesize", json={"text": "bonjour"}).status_code == 401


def test_synthesize_in_mock_mode_returns_text_fallback(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/api/v1/voice/synthesize", json={"text": "Bonjour"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["audio_base64"] is None
    assert body["fallback"] is True
    assert body["provider"] == "gemini"
    assert body["mock"] is True


def test_provider_is_gemini_and_mock_without_key(settings: Settings) -> None:
    provider = GeminiVoiceProvider(settings.model_copy(update={"google_voice": "Charon"}))
    assert provider.mock is True
    assert isinstance(build_voice_provider(settings), GeminiVoiceProvider)


def test_pcm_to_wav_produces_playable_header() -> None:
    wav = pcm_to_wav(b"\x00\x00" * 240)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert len(wav) == 44 + 480

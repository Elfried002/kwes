"""VoiceProvider : ElevenLabs + repli texte explicite (ADR-002).

Aucune clé en dur. Si ELEVENLABS_API_KEY est absente : mode MOCK (pas d'audio,
repli texte, log WARNING, en-tête X-Kwes-Mock: 1). Si l'API échoue : repli
texte sans perdre la conversation ni prétendre qu'un audio a été produit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("kwes.voice")


@dataclass
class VoiceResult:
    text: str
    audio: bytes | None = None
    mime_type: str | None = None
    provider: str = "elevenlabs"
    mock: bool = False
    fallback: bool = True
    reason: str | None = None
    voice_id: str | None = None


class VoiceProvider(Protocol):
    async def synthesize(self, text: str, *, voice_id: str | None = None) -> VoiceResult: ...


class ElevenLabsVoiceProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport
        if settings.voice_is_mock:
            logger.warning(
                "ELEVENLABS_API_KEY absente : VoiceProvider en mode MOCK "
                "(aucun audio généré, repli texte, X-Kwes-Mock: 1)."
            )

    @property
    def mock(self) -> bool:
        return self.settings.voice_is_mock

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> VoiceResult:
        cleaned = (text or "").strip()
        if not cleaned:
            return VoiceResult(text="", fallback=True, reason="Texte vide.", mock=self.mock)

        resolved_voice = voice_id or self.settings.elevenlabs_voice_id
        if self.mock:
            return VoiceResult(
                text=cleaned,
                audio=None,
                mock=True,
                fallback=True,
                reason="ElevenLabs non configuré : réponse en texte uniquement.",
                voice_id=None,
            )
        if not resolved_voice:
            return VoiceResult(
                text=cleaned,
                audio=None,
                mock=False,
                fallback=True,
                reason="Aucune voix ElevenLabs configurée (ELEVENLABS_VOICE_ID absente).",
            )

        url = f"{self.settings.elevenlabs_base_url.rstrip('/')}/v1/text-to-speech/{resolved_voice}"
        params = {"output_format": "mp3_44100_128"}
        headers = {
            "xi-api-key": self.settings.elevenlabs_api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        body = {
            "text": cleaned[:4500],
            "model_id": self.settings.elevenlabs_model_id,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.elevenlabs_timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post(url, json=body, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("ElevenLabs indisponible (%s) : repli texte.", type(exc).__name__)
            return VoiceResult(
                text=cleaned,
                fallback=True,
                reason="Service vocal indisponible : réponse en texte.",
                voice_id=resolved_voice,
            )

        if response.status_code >= 400 or not response.content:
            logger.warning("ElevenLabs status=%s : repli texte.", response.status_code)
            return VoiceResult(
                text=cleaned,
                fallback=True,
                reason="Service vocal indisponible : réponse en texte.",
                voice_id=resolved_voice,
            )

        return VoiceResult(
            text=cleaned,
            audio=response.content,
            mime_type=response.headers.get("content-type", "audio/mpeg"),
            fallback=False,
            voice_id=resolved_voice,
        )


def build_voice_provider(settings: Settings) -> VoiceProvider:
    return ElevenLabsVoiceProvider(settings)

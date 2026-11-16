"""VoiceProvider : ElevenLabs + repli texte explicite (ADR-002).

Aucune clé en dur. Si ELEVENLABS_API_KEY est absente : mode MOCK (pas d'audio,
repli texte, log WARNING, en-tête X-Kwes-Mock: 1). Si l'API échoue : repli
texte sans perdre la conversation ni prétendre qu'un audio a été produit.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("kwes.voice")

# Choix de la voix : le catalogue change rarement, une requête toutes les
# cinq minutes suffit et évite de marteler l'API à chaque ouverture des réglages.
VOICES_CACHE_TTL_SECONDS = 300.0


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


@dataclass(frozen=True)
class VoiceOption:
    """Une voix proposable à l'utilisateur (aucune clé fournisseur dedans)."""

    id: str
    name: str
    gender: str | None = None
    language: str | None = None
    accent: str | None = None
    description: str | None = None
    preview_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "language": self.language,
            "accent": self.accent,
            "description": self.description,
            "preview_url": self.preview_url,
        }


@dataclass
class VoicesResult:
    voices: list[VoiceOption] = field(default_factory=list)
    mock: bool = False
    cached: bool = False
    reason: str | None = None


class VoiceProvider(Protocol):
    async def synthesize(self, text: str, *, voice_id: str | None = None) -> VoiceResult: ...

    async def list_voices(self, *, force: bool = False) -> VoicesResult: ...


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_voice(raw: dict[str, Any]) -> VoiceOption | None:
    """Normalise une voix ElevenLabs ; ignore une entrée sans identifiant."""
    voice_id = _text(raw.get("voice_id"))
    if not voice_id:
        return None
    raw_labels = raw.get("labels")
    labels: dict[str, Any] = raw_labels if isinstance(raw_labels, dict) else {}
    raw_name = _text(raw.get("name")) or voice_id
    # ElevenLabs concatène le descriptif au nom : « George - Warm, Captivating ».
    head, separator, tail = raw_name.partition(" - ")
    name = head.strip() or raw_name
    descriptor = tail.strip() if separator else None
    description = _text(labels.get("descriptive")) or descriptor or _text(raw.get("description"))

    language = _text(labels.get("language"))
    if not language:
        verified = raw.get("verified_languages")
        if isinstance(verified, list):
            for item in verified:
                if isinstance(item, dict) and _text(item.get("language")):
                    language = _text(item.get("language"))
                    break

    return VoiceOption(
        id=voice_id,
        name=name,
        gender=_text(labels.get("gender")),
        language=language,
        accent=_text(labels.get("accent")),
        description=description[:200] if description else None,
        preview_url=_text(raw.get("preview_url")),
    )


class ElevenLabsVoiceProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        voices_ttl_seconds: float = VOICES_CACHE_TTL_SECONDS,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._voices_ttl_seconds = voices_ttl_seconds
        self._voices_cache: tuple[float, VoicesResult] | None = None
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

    async def list_voices(self, *, force: bool = False) -> VoicesResult:
        """Catalogue des voix du compte, avec cache court.

        Jamais d'exception et jamais de clé dans la réponse : en cas d'échec on
        rend ce qu'on a (cache éventuel) et une raison lisible. L'appelant ne
        peut donc pas confondre « aucune voix » et « panne du fournisseur ».
        """
        if self.mock:
            return VoicesResult(
                mock=True,
                reason="ElevenLabs non configuré : aucune voix n'est disponible.",
            )

        cached = self._voices_cache
        if not force and cached and (time.monotonic() - cached[0]) < self._voices_ttl_seconds:
            return replace(cached[1], cached=True)

        url = f"{self.settings.elevenlabs_base_url.rstrip('/')}/v1/voices"
        headers = {"xi-api-key": self.settings.elevenlabs_api_key, "Accept": "application/json"}
        failure = "Catalogue des voix indisponible pour le moment."
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(min(self.settings.elevenlabs_timeout_seconds, 10.0)),
                transport=self._transport,
            ) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("ElevenLabs /v1/voices indisponible (%s).", type(exc).__name__)
            if cached:
                return replace(cached[1], cached=True, reason=failure)
            return VoicesResult(reason=failure)

        if response.status_code >= 400:
            logger.warning("ElevenLabs /v1/voices status=%s.", response.status_code)
            if cached:
                return replace(cached[1], cached=True, reason=failure)
            return VoicesResult(reason=failure)

        try:
            payload = response.json()
        except ValueError:
            logger.warning("ElevenLabs /v1/voices : réponse illisible.")
            return VoicesResult(reason=failure)

        raw_voices = payload.get("voices") if isinstance(payload, dict) else None
        voices: list[VoiceOption] = []
        if isinstance(raw_voices, list):
            for item in raw_voices:
                if not isinstance(item, dict):
                    continue
                parsed = _parse_voice(item)
                if parsed is not None:
                    voices.append(parsed)

        result = VoicesResult(voices=voices, reason=None if voices else "Aucune voix dans ce compte.")
        self._voices_cache = (time.monotonic(), result)
        return result


def build_voice_provider(settings: Settings) -> VoiceProvider:
    return ElevenLabsVoiceProvider(settings)

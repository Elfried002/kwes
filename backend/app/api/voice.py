"""Synthèse vocale (route additive, hors P0) : ElevenLabs avec repli texte.

Le contrat P0 ne liste pas cette route ; elle est ajoutée pour exposer le
VoiceProvider et reste sans effet de bord (aucun stockage d'audio).

GET /voice/voices — catalogue des voix du compte, pour le sélecteur des
réglages. Même fournisseur, même cache court, aucune clé renvoyée.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.api.deps import SettingsDep, UserDep, VoiceDep

router = APIRouter(tags=["voice"])

# Un identifiant ElevenLabs est alphanumérique ; on refuse tout le reste plutôt
# que de l'injecter dans le chemin de l'URL du fournisseur.
VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4500)
    voice_id: str | None = Field(default=None, max_length=64)

    @field_validator("voice_id")
    @classmethod
    def _clean_voice_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not VOICE_ID_PATTERN.match(cleaned):
            raise ValueError("Identifiant de voix invalide.")
        return cleaned


@router.post("/voice/synthesize")
async def synthesize(
    payload: VoiceRequest, user: UserDep, voice: VoiceDep
) -> dict[str, Any]:
    result = await voice.synthesize(payload.text, voice_id=payload.voice_id)
    return {
        "text": result.text,
        "mime_type": result.mime_type,
        "audio_base64": base64.b64encode(result.audio).decode("ascii") if result.audio else None,
        "fallback": result.fallback,
        "reason": result.reason,
        "provider": result.provider,
        "mock": result.mock,
        "voice_id": result.voice_id,
    }


@router.get("/voice/voices")
async def list_voices(user: UserDep, voice: VoiceDep, settings: SettingsDep) -> dict[str, Any]:
    result = await voice.list_voices()
    default_voice = settings.elevenlabs_voice_id.strip() or None
    return {
        "voices": [option.as_dict() for option in result.voices],
        "mock": result.mock,
        "cached": result.cached,
        "reason": result.reason,
        "default_voice_id": None if result.mock else default_voice,
    }

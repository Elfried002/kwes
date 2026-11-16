"""Synthèse vocale (route additive, hors P0) : ElevenLabs avec repli texte.

Le contrat P0 ne liste pas cette route ; elle est ajoutée pour exposer le
VoiceProvider et reste sans effet de bord (aucun stockage d'audio).
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import UserDep, VoiceDep

router = APIRouter(tags=["voice"])


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4500)
    voice_id: str | None = Field(default=None, max_length=64)


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

"""Synthèse vocale Gemini (hors conversation temps réel).

Deux usages dans Kwes :
- la conversation vocale passe par l'API Live (`app/agent/gemini_live.py`) ;
- l'accueil et la prévisualisation des réglages demandent la synthèse ponctuelle
  d'un texte : c'est ce module, via le modèle Live (aucun modèle TTS séparé).

Aucune clé en dur : la clé Google est résolue par `app/core/secrets.py`, qui la
déchiffre depuis `.env` (`GOOGLE_API_KEY_ENC`) au démarrage du processus.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from dataclasses import dataclass, field
from typing import Any, Protocol

from google import genai
from google.genai import types

from app.core.config import Settings

logger = logging.getLogger("kwes.voice")

SAMPLE_RATE = 24000
MAX_TTS_CHARS = 1800

# Catalogue figé (aucun appel réseau pour l'afficher). Le choix final se fait à
# l'oreille : les libellés décrivent un timbre, pas une garantie de genre.
VOICE_CATALOGUE: tuple[tuple[str, str, str], ...] = (
    ("Charon", "Grave, posée", "Timbre profond, débit calme — choix par défaut de Kwes."),
    ("Orus", "Ferme, nette", "Articulation marquée, ton professionnel."),
    ("Fenrir", "Vive, engagée", "Plus énergique, à réserver aux échanges courts."),
    ("Enceladus", "Soufflée, douce", "Timbre plus léger, moins affirmé."),
    ("Iapetus", "Claire, neutre", "Proche d'une lecture d'information."),
    ("Algenib", "Rauque", "Grain marqué, moins institutionnel."),
    ("Puck", "Jeune, légère", "Débit rapide, peu adapté à un ton posé."),
    ("Kore", "Claire, posée", "Voix alternative pour comparer."),
)


@dataclass
class VoiceResult:
    text: str
    audio: bytes | None = None
    mime_type: str | None = None
    provider: str = "gemini"
    mock: bool = False
    fallback: bool = True
    reason: str | None = None
    voice_id: str | None = None


@dataclass(frozen=True)
class VoiceOption:
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


def catalogue() -> list[VoiceOption]:
    return [
        VoiceOption(id=name, name=name, description=f"{label} — {detail}", language="fr, en")
        for name, label, detail in VOICE_CATALOGUE
    ]


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


class GeminiVoiceProvider:
    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client
        if not settings.gemini_api_key:
            logger.warning("Clé Google absente : synthèse vocale indisponible (repli texte).")

    @property
    def mock(self) -> bool:
        return not bool(self.settings.gemini_api_key)

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        return genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options={"api_version": "v1beta"},
        )

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> VoiceResult:
        cleaned = (text or "").strip()
        if not cleaned:
            return VoiceResult(text="", fallback=True, reason="Texte vide.", mock=self.mock)

        known = {item[0] for item in VOICE_CATALOGUE}
        voice = (voice_id or self.settings.google_voice or "Charon").strip()
        if voice not in known:
            voice = self.settings.google_voice or "Charon"

        if self.mock:
            return VoiceResult(
                text=cleaned,
                mock=True,
                fallback=True,
                reason="Service vocal non configuré : réponse en texte uniquement.",
            )

        # Pas de modèle TTS séparé : le brief n'autorise que les deux modèles
        # Live. On demande au modèle rapide de lire le texte, et on garde l'audio.
        try:
            client = self._client_or_raise()
            audio = await asyncio.wait_for(
                self._speak_live(client, cleaned[:MAX_TTS_CHARS], voice), timeout=60
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synthèse Gemini indisponible (%s).", type(exc).__name__)
            return VoiceResult(
                text=cleaned,
                fallback=True,
                reason="Service vocal indisponible : réponse en texte.",
                voice_id=voice,
            )

        if not audio:
            return VoiceResult(
                text=cleaned,
                fallback=True,
                reason="Le service vocal n'a renvoyé aucun audio.",
                voice_id=voice,
            )

        return VoiceResult(
            text=cleaned,
            audio=pcm_to_wav(audio),
            mime_type="audio/wav",
            fallback=False,
            voice_id=voice,
        )

    async def _speak_live(self, client: Any, text: str, voice: str) -> bytes:
        """Lit un texte via le modèle Live et renvoie le PCM 24 kHz brut.

        Aucun modèle TTS séparé : le brief n'autorise que les deux modèles Live.
        """
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text="Lis le texte fourni exactement, sans rien ajouter.")]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        )
        audio = b""
        async with client.aio.live.connect(model=self.settings.google_live_model, config=config) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=f"Lis ceci :\n{text}")]),
                turn_complete=True,
            )
            async for message in session.receive():
                content = getattr(message, "server_content", None)
                if content is None:
                    continue
                for part in getattr(getattr(content, "model_turn", None), "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        audio += inline.data
                if getattr(content, "turn_complete", False):
                    break
        return audio

    async def list_voices(self, *, force: bool = False) -> VoicesResult:
        return VoicesResult(
            voices=catalogue(),
            mock=self.mock,
            reason="Service vocal non configuré." if self.mock else None,
        )


def build_voice_provider(settings: Settings) -> VoiceProvider:
    return GeminiVoiceProvider(settings)

"""Génère le même message avec plusieurs voix Gemini pour choisir à l'oreille.

Sortie : un WAV par voix dans /tmp/voix/. Aucune donnée sensible.
"""

import asyncio
import wave
from pathlib import Path

from google import genai
from google.genai import types

from app.core.config import Settings

settings = Settings()
OUT = Path("/tmp/voix")
OUT.mkdir(exist_ok=True)

PHRASE = (
    "Bonjour Elfried. J'ai vérifié le prix du cacao : il est fixé à mille deux cents "
    "francs le kilo pour cette campagne. Veux-tu que je regarde aussi les cours mondiaux ?"
)

VOIX = ["Charon", "Kore", "Aoede", "Puck"]


async def sample(voice: str) -> None:
    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options={"api_version": "v1beta", "timeout": 45000},
    )
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part(text="Tu es Kwes. Tu parles français, avec naturel et chaleur.")]
        ),
    )
    chunks: list[bytes] = []
    async with client.aio.live.connect(model=settings.google_live_model, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=PHRASE)]),
            turn_complete=True,
        )
        async for message in session.receive():
            content = getattr(message, "server_content", None)
            if content is None:
                continue
            data = getattr(content, "model_turn", None)
            if data is not None:
                for part in getattr(data, "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and getattr(inline, "data", None):
                        chunks.append(inline.data)
            if getattr(content, "turn_complete", False):
                break

    audio = b"".join(chunks)
    path = OUT / f"{voice.lower()}.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(audio)
    print(f"{voice}: {len(audio) / 48000:.1f} s -> {path}")


async def main() -> None:
    for voice in VOIX:
        try:
            await sample(voice)
        except Exception as exc:  # noqa: BLE001
            print(f"{voice}: ÉCHEC {type(exc).__name__} {str(exc)[:120]}")


asyncio.run(main())

#!/usr/bin/env python3
"""Sonde Gemini Live — vérifie la connexion, la voix et la prononciation.

Usage : python tools/gemini_probe.py [voice ...]
Écrit des WAV 24 kHz mono dans .probe/ et affiche la durée, sans jamais
afficher la clé.
"""
from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from google import genai
from google.genai import types

from app.core.secrets import resolve_secret

MODEL = "gemini-3.8-live"
OUT = Path(__file__).resolve().parents[1] / ".probe"

SYSTEM = """Tu es Kwes, l'assistant personnel de l'utilisateur.
Le nom de l'agent est Kwes. Sa prononciation officielle est /kwɛs/ : prononce
distinctement la consonne finale /s/. Ne supprime jamais le son final. Ne
prononce pas ce nom comme « Kwè ». Le nom doit être prononcé avec une première
syllabe « kwè » suivie d'un « s » final nettement audible, en français comme en
anglais.
Réponds en français, brièvement, d'une voix calme et posée.
"""

PHRASES = [
    "Bonjour, je suis Kwes, ton assistant personnel.",
    "Tu peux compter sur Kwes pour organiser ton travail.",
    "Kwes est prêt à exécuter cette tâche.",
    "Je suis Kwes. Comment puis-je t'aider aujourd'hui ?",
]


def write_wav(path: Path, pcm: bytes, rate: int = 24000) -> float:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return len(pcm) / (rate * 2)


async def speak(client: genai.Client, voice: str, phrase: str, out: Path) -> tuple[int, float]:
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    audio = bytearray()
    transcript = ""
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=f"Dis exactement : {phrase}")]),
            turn_complete=True,
        )
        async for message in session.receive():
            if getattr(message, "data", None):
                audio.extend(message.data)
            content = getattr(message, "server_content", None)
            if content and getattr(content, "output_transcription", None):
                transcript += content.output_transcription.text or ""
            if content and getattr(content, "turn_complete", False):
                break
    out.write_bytes(bytes(audio))
    duration = write_wav(out.with_suffix(".wav"), bytes(audio))
    print(f"  {out.with_suffix('.wav').name}: {len(audio)} octets, {duration:.2f}s")
    if transcript.strip():
        print(f"  transcription modèle : {transcript.strip()[:120]}")
    return len(audio), duration


async def main() -> int:
    voices = sys.argv[1:] or ["Charon"]
    key = resolve_secret("GOOGLE_API_KEY")
    if not key:
        print("clé Google absente")
        return 2
    OUT.mkdir(exist_ok=True)
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})

    for voice in voices:
        print(f"voix {voice}")
        for index, phrase in enumerate(PHRASES, start=1):
            started = time.monotonic()
            try:
                size, _ = await speak(client, voice, phrase, OUT / f"{voice}-{index}.pcm")
                print(f"  ({time.monotonic() - started:.1f}s)")
                if size == 0:
                    print("  aucun audio reçu")
            except Exception as exc:  # noqa: BLE001
                print(f"  échec: {type(exc).__name__}: {str(exc)[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

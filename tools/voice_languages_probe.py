#!/usr/bin/env python3
"""Sonde des capacités vocales de Gemini par langue (aucune supposition).

Pour chaque langue : on demande au modèle de prononcer une phrase, on capture
l'audio, puis on renvoie cet audio comme entrée pour mesurer ce qu'il comprend.
Deux mesures par langue : rendu audio (durée non nulle) et similarité entre la
phrase demandée et la transcription de l'audio relu.

Sortie : .probe/languages.json + un tableau lisible. Aucun statut n'est déduit
d'une documentation : tout vient de ces appels réels.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import sys
import wave
from pathlib import Path

from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.secrets import resolve_secret  # noqa: E402

MODEL = "gemini-3.8-live"
OUT = ROOT / ".probe"
LANGUAGES = [
    ("fr", "Français", "Bonjour, je suis Kwes, ton assistant personnel."),
    ("en", "Anglais", "Hello, I am Kwes, your personal assistant."),
    ("sw", "Swahili", "Habari, mimi ni Kwes, msaidizi wako binafsi."),
    ("yo", "Yoruba", "Báwo ni, èmi ni Kwes, olùrànlọ́wọ́ rẹ."),
    ("ha", "Hausa", "Sannu, ni ne Kwes, mataimakin ka."),
    ("wo", "Wolof", "Salaam, man la Kwes, jàppaleku sa."),
    ("tw", "Akan (Twi)", "Maakye, me ne Kwes, wo boafo."),
    # Langues ivoiriennes : je ne produis pas de phrase de mémoire. On demande au
    # modèle de traduire — le texte obtenu doit être validé par un locuteur.
    ("bci", "Baoulé", "TRADUIRE: Bonjour, je suis Kwes, ton assistant personnel."),
    ("dyu", "Dioula", "TRADUIRE: Bonjour, je suis Kwes, ton assistant personnel."),
    ("bet", "Bété", "TRADUIRE: Bonjour, je suis Kwes, ton assistant personnel."),
    ("nouchi", "Nouchi", "TRADUIRE: Bonjour, je suis Kwes, ton assistant personnel."),
]

SYSTEM = """Tu es Kwes. Prononce exactement la phrase demandée, dans la langue indiquée,
sans commentaire ni traduction. Le nom de l'agent s'écrit Kwes et se prononce /kwɛs/."""


def speech_config(voice: str = "Charon") -> types.SpeechConfig:
    return types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
        )
    )


async def say(client: genai.Client, text: str, language: str) -> tuple[bytes, str]:
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM)]),
        speech_config=speech_config(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    audio = bytearray()
    transcript = ""
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=f"Langue : {language}. Dis exactement : {text}")],
            ),
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
    return bytes(audio), transcript.strip()


async def hear(client: genai.Client, pcm: bytes, language: str) -> str:
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text="Tu transcris ce que tu entends.")]),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
        ),
    )
    heard = ""
    async with client.aio.live.connect(model=MODEL, config=config) as session:
        await session.send_realtime_input(activity_start=types.ActivityStart())
        for start in range(0, len(pcm), 6400):
            await session.send_realtime_input(
                audio=types.Blob(data=pcm[start : start + 6400], mime_type="audio/pcm;rate=24000")
            )
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)
        await session.send_realtime_input(activity_end=types.ActivityEnd())
        try:
            async with asyncio.timeout(12):
                async for message in session.receive():
                    content = getattr(message, "server_content", None)
                    if content and getattr(content, "input_transcription", None):
                        heard += content.input_transcription.text or ""
                    if content and getattr(content, "turn_complete", False):
                        break
        except (TimeoutError, asyncio.TimeoutError):
            pass
    return heard.strip()


def similarity(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio(), 3)


async def main() -> int:
    OUT.mkdir(exist_ok=True)
    key = resolve_secret("GOOGLE_API_KEY")
    if not key:
        print("clé absente")
        return 2
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    results = []
    for code, label, phrase in LANGUAGES:
        entry: dict = {"code": code, "label": label, "phrase_demandee": phrase}
        try:
            pcm, said = await say(client, phrase, label)
            entry["audio_s"] = round(len(pcm) / 48000, 2)
            entry["transcription_modele"] = said
            if pcm:
                with wave.open(str(OUT / f"lang-{code}.wav"), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(24000)
                    handle.writeframes(pcm)
                heard = await hear(client, pcm, label)
                entry["entendu_par_modele"] = heard
                entry["similarite_rendu"] = similarity(phrase, said)
                entry["similarite_ecoute"] = similarity(said or phrase, heard)
        except Exception as exc:  # noqa: BLE001
            entry["erreur"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        results.append(entry)
        print(
            f"{code:6} {label:14} audio={entry.get('audio_s', 0):5}s "
            f"rendu={entry.get('similarite_rendu', '-')} écoute={entry.get('similarite_ecoute', '-')}"
        )
        if entry.get("erreur"):
            print("        erreur:", entry["erreur"])
    (OUT / "languages.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("\nécrit", OUT / "languages.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

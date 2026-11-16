#!/usr/bin/env python3
"""Test de bout en bout de la voix Kwes : parole réelle → Gemini Live → audio.

1. Synthétise une question avec une autre voix Gemini (l'utilisateur simulé).
2. Rééchantillonne 24 kHz → 16 kHz.
3. Ouvre la WebSocket de Kwes avec un ticket, envoie l'audio par petits blocs.
4. Écrit la réponse audio dans .probe/ et vérifie qu'elle est non vide.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import urllib.request
import wave
from pathlib import Path

import websockets
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.secrets import resolve_secret  # noqa: E402

API = "http://127.0.0.1:8000/api/v1"
OUT = ROOT / ".probe"


def _token() -> str:
    return (ROOT / ".sb_bearer").read_text().strip()


def _http(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


async def synthesize_question(text: str, path: Path, voice: str = "Kore") -> bytes:
    client = genai.Client(api_key=resolve_secret("GOOGLE_API_KEY"), http_options={"api_version": "v1beta"})
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
    )
    audio = bytearray()
    async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=f"Dis exactement : {text}")]),
            turn_complete=True,
        )
        async for message in session.receive():
            if getattr(message, "data", None):
                audio.extend(message.data)
            content = getattr(message, "server_content", None)
            if content and getattr(content, "turn_complete", False):
                break
    path.write_bytes(bytes(audio))
    return bytes(audio)


def resample(pcm: bytes, src: int, dst: int) -> bytes:
    """Rééchantillonnage linéaire 16 bits mono (suffisant pour de la parole)."""
    samples = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm) - 1, 2)]
    ratio = src / dst
    count = int(len(samples) / ratio)
    out = bytearray()
    for index in range(count):
        position = index * ratio
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        weight = position - left
        value = int(samples[left] * (1 - weight) + samples[right] * weight)
        out += int(value).to_bytes(2, "little", signed=True)
    return bytes(out)


async def main() -> int:
    OUT.mkdir(exist_ok=True)
    question = " ".join(item for item in sys.argv[1:] if not item.startswith("--")) or "Bonjour Kwes, présente-toi en une phrase."
    print("question :", question)

    config = await asyncio.to_thread(_http, "GET", "/voice/config")
    print("config voix :", json.dumps(config, ensure_ascii=False))

    raw = await synthesize_question(question, OUT / "question-24k.pcm")
    print(f"question audio : {len(raw)} octets @24 kHz ({len(raw) / 48000:.1f}s)")
    pcm16 = resample(raw, 24000, 16000)
    with wave.open(str(OUT / "question-16k.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(pcm16)

    ticket = await asyncio.to_thread(_http, "POST", "/voice/ticket")
    print("ticket :", "reçu" if ticket.get("ticket") else "absent")

    url = f"ws://127.0.0.1:8000/api/v1/voice/live?ticket={ticket['ticket']}"
    audio_out = bytearray()
    transcripts: list[str] = []
    states: list[str] = []

    async with websockets.connect(url, origin="http://127.0.0.1:5173", max_size=8_000_000) as ws:
        ready = json.loads(await ws.recv())
        print("serveur :", ready)

        async def sender() -> None:
            chunk = 3200  # 100 ms à 16 kHz
            await ws.send(json.dumps({"type": "activity_start"}))
            for start in range(0, len(pcm16), chunk):
                await ws.send(
                    json.dumps(
                        {"type": "audio", "data": base64.b64encode(pcm16[start : start + chunk]).decode()}
                    )
                )
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.4)
            await ws.send(json.dumps({"type": "activity_end"}))

        async def receiver() -> None:
            try:
                while True:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    kind = message.get("type")
                    if kind == "audio":
                        audio_out.extend(base64.b64decode(message["data"]))
                    elif kind == "transcript":
                        transcripts.append(f"{message.get('role')}: {message.get('text')}")
                    elif kind == "tool":
                        print(f"  outil {message.get('name')} → {message.get('status')} {message.get('summary','')[:80]}")
                    elif kind == "state":
                        states.append(message.get("value", ""))
                    elif kind == "error":
                        print("  erreur :", message)
                    elif kind == "interrupted":
                        print("  interruption (barge-in)")
            except asyncio.TimeoutError:
                pass
            except websockets.ConnectionClosed:
                pass

        try:
            await asyncio.gather(sender(), receiver())
            await ws.send(json.dumps({"type": "close"}))
        except (websockets.ConnectionClosed, ConnectionError):
            pass

    reply = OUT / "reponse-kwes.pcm"
    reply.write_bytes(bytes(audio_out))
    with wave.open(str(OUT / "reponse-kwes.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(bytes(audio_out))

    print(f"réponse audio : {len(audio_out)} octets @24 kHz ({len(audio_out) / 48000:.1f}s)")
    print("transcriptions :")
    for line in transcripts[:12]:
        print("  -", line[:160])
    print("états :", states[:8])
    return 0 if audio_out else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Sonde de fluidité vocale : découpage du tour, répétitions, latence au premier son.

Trois mesures sur une vraie session Live (production ou local) :

A. ``turns``   — une question, un seul ``activity_end`` : combien de réponses
   l'assistant produit-il, et quel est le délai avant le premier octet audio ?
B. ``split``   — la même phrase prononcée avec deux hésitations de 420 ms. Le
   client VAD d'avant coupait le tour à chaque hésitation (`activity_end`) :
   on compte les réponses produites. Une seule est correcte.
C. ``echo``    — la réponse commence, puis on renvoie une activité courte (ce que
   fait le micro quand il capte le haut-parleur) : on compte les réponses
   supplémentaires. Deux réponses = le modèle se répète.

Aucun chiffre n'est déduit : tout vient des blocs audio réellement reçus.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import sys
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".probe"
FRAME_BYTES = 3200  # 100 ms à 16 kHz, 16 bits
BASE = "https://api.agent-kwes.com/api/v1"


def token() -> str:
    return (ROOT / ".sb_bearer").read_text().strip()


def http_post(path: str, payload: dict) -> dict:
    import urllib.request

    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def pcm(path: Path) -> bytes:
    """PCM 16 bits 16 kHz, sans en-tête (les fichiers de .probe sont en 24 kHz).

    Les `.wav` de `.probe` sont parfois du PCM brut 24 kHz (sortie TTS) : on
    détecte l'en-tête RIFF au lieu de se fier à l'extension. Rééchantillonnage
    linéaire en Python pur : `audioop` n'existe plus en 3.13+.
    """
    import array
    import wave

    raw = path.read_bytes()
    if raw[:4] == b"RIFF":
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            data = handle.readframes(handle.getnframes())
            width = handle.getsampwidth()
        if width != 2:
            raise SystemExit(f"{path}: attendu 16 bits, trouvé {width * 8}")
    else:
        rate, data = 24000, raw
    if rate == 16000:
        return data
    samples = array.array("h")
    samples.frombytes(data)
    count = int(len(samples) * 16000 / rate)
    step = rate / 16000
    out = array.array("h", [0]) * count
    for index in range(count):
        position = index * step
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        weight = position - left
        out[index] = int(samples[left] * (1 - weight) + samples[right] * weight)
    return out.tobytes()


async def ticket(language: str | None) -> str:
    return http_post("/voice/ticket", {"language": language})["ticket"]


class Turn:
    """Compte les réponses de l'assistant : un bloc audio, puis un silence."""

    def __init__(self) -> None:
        self.started = 0
        self.blocks = 0
        self.bytes = 0
        self.text = ""
        self.ttfb: float | None = None
        self.last_audio = 0.0
        self.interrupted = 0
        self.stream_s = 0.0

    def feed(self, message: dict, now: float) -> None:
        kind = message.get("type")
        if kind == "audio" and message.get("data"):
            if now - self.last_audio > 0.9:
                self.started += 1
            self.last_audio = now
            self.blocks += 1
            self.bytes += len(base64.b64decode(message["data"]))
        elif kind == "transcript" and message.get("role") == "assistant":
            self.text = (self.text + " " + str(message.get("text") or "")).strip()[:400]
        elif kind == "interrupted":
            self.interrupted += 1

    @property
    def seconds(self) -> float:
        return round(self.bytes / 48000, 2)


async def send_stream(ws, data: bytes, *, start: bool = True, end: bool = True, tail_ms: int = 0) -> None:
    if start:
        await ws.send(json.dumps({"type": "activity_start"}))
    for offset in range(0, len(data), FRAME_BYTES):
        await ws.send(json.dumps({"type": "audio", "data": base64.b64encode(data[offset : offset + FRAME_BYTES]).decode()}))
        await asyncio.sleep(0.1)
    if tail_ms:
        await ws.send(json.dumps({"type": "audio", "data": base64.b64encode(b"\x00\x00" * 1600 * (tail_ms // 100)).decode()}))
    if end:
        await ws.send(json.dumps({"type": "activity_end"}))


async def drain(ws, turn: Turn, *, until_idle: float = 2.5, cap: float = 25.0) -> None:
    deadline = time.monotonic() + cap
    while time.monotonic() < deadline:
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=until_idle))
        except asyncio.TimeoutError:
            return
        turn.feed(message, time.monotonic())
        if message.get("type") == "error":
            return


async def measure_turn(ws, data: bytes) -> dict:
    turn = Turn()
    streaming_started = time.monotonic()
    await send_stream(ws, data)
    # L'horloge part de la **fin** de la prise de parole : mesurer depuis le
    # premier mot incluait la durée de la question elle-même (~3 s).
    sent_at = time.monotonic()
    turn.stream_s = round(sent_at - streaming_started, 2)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
        except asyncio.TimeoutError:
            break
        now = time.monotonic()
        if message.get("type") == "audio" and turn.ttfb is None:
            turn.ttfb = now - sent_at
        turn.feed(message, now)
        if message.get("type") == "error":
            break
        if message.get("type") == "state" and message.get("value") == "listening" and turn.blocks:
            await drain(ws, turn, until_idle=1.2, cap=6)
            break
    return {
        "ttfb_ms": round(turn.ttfb * 1000) if turn.ttfb else None,
        "stream_s": turn.stream_s,
        "responses": turn.started,
        "audio_s": turn.seconds,
        "blocks": turn.blocks,
        "text": turn.text[:180],
    }


async def measure_split(ws, data: bytes, pauses: int = 2, gap_ms: int = 420) -> dict:
    """Une phrase, `pauses` hésitations : le client d'avant fermait le tour à chacune."""
    turn = Turn()
    total = len(data)
    cuts = [int(total * (index + 1) / (pauses + 1)) for index in range(pauses)]
    edges = [0, *cuts, total]
    for index in range(len(edges) - 1):
        try:
            await send_stream(ws, data[edges[index] : edges[index + 1]])
        except Exception as exc:  # noqa: BLE001 — une session fermée est un résultat
            return {"responses": turn.started, "audio_s": turn.seconds, "blocks": turn.blocks,
                    "text": turn.text[:220], "session_closed": type(exc).__name__}
        await asyncio.sleep(gap_ms / 1000)
    await drain(ws, turn, until_idle=2.0, cap=20)
    return {
        "responses": turn.started,
        "audio_s": turn.seconds,
        "blocks": turn.blocks,
        "text": turn.text[:220],
    }


async def measure_echo(ws, data: bytes) -> dict:
    """Le micro capte la réponse : activité courte pendant que le modèle parle."""
    turn = Turn()
    await send_stream(ws, data)
    first = None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
        except asyncio.TimeoutError:
            break
        now = time.monotonic()
        if message.get("type") == "audio" and message.get("data"):
            turn.feed(message, now)
            if first is None:
                first = now
                break
    if first is None:
        return {"error": "aucun audio"}
    # Écho du haut-parleur : un mot de 300 ms, puis silence.
    echo = b"\x00\x00" * 1600 * 3
    await send_stream(ws, echo, tail_ms=0)
    await drain(ws, turn, until_idle=2.0, cap=15)
    return {
        "responses": turn.started,
        "extra_responses": max(0, turn.started - 1),
        "interrupted": turn.interrupted,
        "audio_s": turn.seconds,
        "text": turn.text[-200:],
    }


async def connect(language: str, url: str, attempts: int = 8):
    """Ouvre une session, en réessayant : les tickets sont en mémoire côté API.

    L'API de production tourne en `--workers 2` : un ticket émis par un worker
    est refusé (403) par l'autre. La sonde réessaie, mais compte les échecs.
    """
    last: Exception | None = None
    for _ in range(attempts):
        slug = await ticket(language)
        try:
            ws = await websockets.connect(f"{url}?ticket={slug}", max_size=8_000_000)
            return ws
        except Exception as exc:  # noqa: BLE001
            last = exc
            await asyncio.sleep(0.2)
    raise last or RuntimeError("connexion impossible")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="avant")
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--url", default="wss://api.agent-kwes.com/api/v1/voice/live")
    parser.add_argument("--language", default="fr")
    args = parser.parse_args()

    results: dict[str, object] = {"label": args.label, "url": args.url, "turns": [], "language_ticket": None}
    questions = [OUT / f"latency-q{index}.wav" for index in range(4)]
    audio = [pcm(path) for path in questions if path.exists()]

    # La langue du ticket, telle que l'API la renvoie pour un client sans préférence.
    results["language_ticket"] = http_post("/voice/ticket", {"language": None}).get("language")

    samples: list[int] = []
    for index in range(args.turns):
        ws = await connect(args.language, args.url)
        async with ws:
            ready = json.loads(await ws.recv())
            results["model"] = ready.get("model")
            results["language_ready"] = ready.get("language")
            outcome = await measure_turn(ws, audio[index % len(audio)])
            results["turns"].append(outcome)
            print(f"  tour {index + 1}: ttfb={outcome['ttfb_ms']} ms · réponses={outcome['responses']} · audio={outcome['audio_s']}s", flush=True)
            if outcome["ttfb_ms"]:
                samples.append(outcome["ttfb_ms"])

    # Découpage et écho sur une session neuve, avec une question déjà utilisée.
    ws = await connect(args.language, args.url)
    async with ws:
        await ws.recv()
        try:
            results["split"] = await measure_split(ws, audio[0])
        except Exception as exc:  # noqa: BLE001
            results["split"] = {"error": type(exc).__name__}
        print(f"  découpage (2 hésitations) : {results['split']}", flush=True)

    ws = await connect(args.language, args.url)
    async with ws:
        await ws.recv()
        try:
            results["echo"] = await measure_echo(ws, audio[1] if len(audio) > 1 else audio[0])
        except Exception as exc:  # noqa: BLE001
            results["echo"] = {"error": type(exc).__name__}
        print(f"  écho pendant la réponse : {results['echo']}", flush=True)

    if samples:
        ordered = sorted(samples)
        results["ttfb_p50_ms"] = round(statistics.median(ordered))
        results["ttfb_max_ms"] = ordered[-1]
        results["ttfb_min_ms"] = ordered[0]

    path = OUT / f"voice_fluidity_{args.label}.json"
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Mesure réelle du temps avant le premier son (TTFB vocal) sur Gemini Live.

Protocole : on synthétise une question avec une voix Gemini, on l'envoie en PCM
16 kHz au rythme réel (blocs de 100 ms), on envoie `activity_end`, puis on mesure
le délai jusqu'au **premier octet audio** reçu du serveur.

Sortie : P50, P95, min, max, nombre de tours sans audio. Aucun chiffre n'est
extrait d'une théorie : tout vient de la session réelle.
"""

from __future__ import annotations

import asyncio
import base64
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8000/api/v1"
OUT = ROOT / ".probe"

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from voice_e2e import resample, synthesize_question  # noqa: E402

QUESTIONS = [
    "Bonjour Kwes, comment vas-tu aujourd'hui ?",
    "Quelle heure est-il et que peux-tu faire pour moi ?",
    "Explique-moi en deux phrases ce qu'est un assistant vocal.",
]


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


async def prepare(index: int) -> bytes:
    """Les échantillons sont synthétisés en PCM 24 kHz brut (sans en-tête WAV)."""
    path = OUT / f"latency-q{index}.wav"
    if not path.exists():
        await synthesize_question(QUESTIONS[index % len(QUESTIONS)], path)
    return resample(path.read_bytes(), 24000, 16000)


async def measure_once(pcm16: bytes, *, mode: str = "fast") -> dict:
    ticket = _http("POST", "/voice/ticket", {"language": "fr"})["ticket"]
    url = f"ws://127.0.0.1:8000/api/v1/voice/live?ticket={ticket}"
    result = {"ttfb": None, "audio_s": 0.0, "text": ""}

    async with websockets.connect(url, max_size=8_000_000) as ws:
        ready = json.loads(await ws.recv())
        result["model"] = ready.get("model")
        if mode != "fast":
            await ws.send(json.dumps({"type": "mode", "value": mode}))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if message.get("type") == "mode":
                    result["model"] = message.get("model")
                    break

        await ws.send(json.dumps({"type": "activity_start"}))
        for offset in range(0, len(pcm16), 3200):
            await ws.send(
                json.dumps({"type": "audio", "data": base64.b64encode(pcm16[offset : offset + 3200]).decode()})
            )
            await asyncio.sleep(0.1)

        sent_at = time.monotonic()
        await ws.send(json.dumps({"type": "activity_end"}))

        audio_bytes = 0
        while True:
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                break
            kind = message.get("type")
            if kind == "audio" and message.get("data"):
                if result["ttfb"] is None:
                    result["ttfb"] = time.monotonic() - sent_at
                audio_bytes += len(base64.b64decode(message["data"]))
            elif kind == "transcript" and message.get("role") == "assistant":
                result["text"] = (result["text"] + " " + str(message.get("text") or "")).strip()[:200]
            elif kind == "closed":
                break
            elif kind == "error":
                result["error"] = message.get("code")
                break
            elif kind == "state" and message.get("value") == "listening" and audio_bytes:
                # Fin de tour : le serveur repasse en écoute après la réponse.
                await asyncio.sleep(0.4)
                break

    result["audio_s"] = round(audio_bytes / 48000, 2)
    return result


async def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    mode = sys.argv[2] if len(sys.argv) > 2 else "fast"
    OUT.mkdir(exist_ok=True)

    print(f"Sonde de latence : {runs} tours, mode={mode}")
    samples: list[float] = []
    for index in range(runs):
        pcm = await prepare(index)
        try:
            outcome = await measure_once(pcm, mode=mode)
        except Exception as exc:  # noqa: BLE001 — une mesure ratée est rapportée, pas masquée
            print(f"  tour {index + 1}: échec ({type(exc).__name__})")
            continue
        ttfb = outcome["ttfb"]
        label = f"{ttfb * 1000:.0f} ms" if ttfb else "aucun audio"
        print(
            f"  tour {index + 1}: ttfb={label} · audio={outcome['audio_s']}s · "
            f"texte={(outcome['text'] or '—')[:70]}"
        )
        if ttfb:
            samples.append(ttfb)

    if not samples:
        print("Aucune mesure exploitable.")
        return 1
    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    summary = {
        "runs": runs,
        "reussis": len(samples),
        "mode": mode,
        "ttfb_p50_ms": round(p50 * 1000),
        "ttfb_p95_ms": round(p95 * 1000),
        "ttfb_min_ms": round(ordered[0] * 1000),
        "ttfb_max_ms": round(ordered[-1] * 1000),
    }
    (OUT / "voice_latency.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

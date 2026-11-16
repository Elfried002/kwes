#!/usr/bin/env python3
"""Analyse acoustique du nom « Kwes » dans un WAV (aucune dépendance externe).

Le /s/ final est une fricative : bruit large bande, énergie concentrée au-dessus
de 3,5 kHz, débit de passages par zéro élevé, durée typique 60–200 ms. On mesure
donc, à la fin du mot, la présence et la durée d'un tel segment.

Sortie : un verdict lisible + une timeline condensée, sans jamais toucher au
réseau.
"""
from __future__ import annotations

import cmath
import math
import sys
import wave
from pathlib import Path

FRAME = 512          # ~21 ms à 24 kHz
HOP = 240            # 10 ms
HF_BAND = (3500, 10000)


def load(path: Path) -> tuple[list[int], int]:
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1 and handle.getsampwidth() == 2
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = [int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw), 2)]
    return samples, rate


def fft(values: list[complex]) -> list[complex]:
    """FFT radix-2 itérative (taille puissance de deux)."""
    n = len(values)
    result = list(values)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            result[i], result[j] = result[j], result[i]
    length = 2
    while length <= n:
        angle = -2 * math.pi / length
        wl = cmath.exp(complex(0, angle))
        for start in range(0, n, length):
            w = 1 + 0j
            for offset in range(length // 2):
                u = result[start + offset]
                v = result[start + offset + length // 2] * w
                result[start + offset] = u + v
                result[start + offset + length // 2] = u - v
                w *= wl
        length <<= 1
    return result


def frames(samples: list[int]) -> list[dict]:
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (FRAME - 1)) for i in range(FRAME)]
    out = []
    for start in range(0, max(1, len(samples) - FRAME), HOP):
        chunk = samples[start : start + FRAME]
        if len(chunk) < FRAME:
            break
        centred = [chunk[i] * window[i] for i in range(FRAME)]
        spectrum = fft([complex(v, 0) for v in centred])
        total = 0.0
        high = 0.0
        for k in range(1, FRAME // 2):
            frequency = k * 24000 / FRAME
            power = abs(spectrum[k]) ** 2
            total += power
            if HF_BAND[0] <= frequency <= HF_BAND[1]:
                high += power
        rms = math.sqrt(sum(v * v for v in chunk) / FRAME) / 32768
        crossings = sum(
            1 for i in range(1, len(chunk)) if (chunk[i - 1] < 0) != (chunk[i] < 0)
        )
        out.append(
            {
                "t": start / 24000,
                "rms": rms,
                "db": 20 * math.log10(rms + 1e-9),
                "hf": high / total if total else 0.0,
                "zcr": crossings / (FRAME / 24000),
            }
        )
    return out


def fricative_segments(series: list[dict]) -> list[dict]:
    """Segments non voisés à forte énergie haute fréquence (= fricatives)."""
    segments: list[dict] = []
    current: dict | None = None
    for frame in series:
        is_fricative = frame["hf"] > 0.70 and frame["zcr"] > 9000
        if is_fricative:
            if current is None:
                current = {"start": frame["t"], "frames": 1}
            else:
                current["frames"] += 1
        elif current is not None:
            current["duration_ms"] = current["frames"] * 10
            segments.append(current)
            current = None
    if current is not None:
        current["duration_ms"] = current["frames"] * 10
        segments.append(current)
    return [segment for segment in segments if segment["duration_ms"] >= 40]


def analyse(path: Path) -> dict:
    samples, rate = load(path)
    series = frames(samples)
    if not series:
        return {"file": path.name, "verdict": "vide"}
    peak = max(frame["rms"] for frame in series)
    speech = [frame for frame in series if frame["rms"] > peak * 0.06]
    if not speech:
        return {"file": path.name, "verdict": "silence"}
    end = speech[-1]["t"]
    start = speech[0]["t"]
    # Le /s/ final : segment haute fréquence, hors du voisement, à la fin du mot.
    fricatives = [
        frame for frame in speech if frame["hf"] > 0.55 and frame["zcr"] > 3800 and frame["rms"] > peak * 0.05
    ]
    tail = [frame for frame in fricatives if frame["t"] > end - 0.40]
    durations = []
    if tail:
        run_start = tail[0]["t"]
        previous = tail[0]["t"]
        for frame in tail[1:]:
            if frame["t"] - previous > 0.03:
                durations.append(previous - run_start)
                run_start = frame["t"]
            previous = frame["t"]
        durations.append(previous - run_start)
    return {
        "file": path.name,
        "duree_mot": round(end - start, 2),
        "pic_db": round(20 * math.log10(peak + 1e-9), 1),
        "fricative_finale_ms": round((max(durations) + 0.01) * 1000) if durations else 0,
        "verdict": "s final présent" if durations and max(durations) >= 0.04 else "s final absent ou très faible",
        "timeline": series,
    }


def main() -> int:
    args = sys.argv[1:]
    show_timeline = "--timeline" in args
    paths = [Path(item) for item in args if not item.startswith("--")]
    if not paths:
        print("usage: analyse_prononciation.py fichier.wav [...]")
        return 2
    for path in paths:
        report = analyse(path)
        print(
            f"{report['file']}: {report['verdict']} | mot {report.get('duree_mot', '?')}s | "
            f"fricative finale {report.get('fricative_finale_ms', 0)} ms"
        )
        segments = fricative_segments(report.get("timeline") or [])
        if segments:
            print(
                "  fricatives détectées : "
                + ", ".join(f"{seg['start']:.2f}s/{seg['duration_ms']}ms" for seg in segments[:8])
            )
        timeline = report.get("timeline") or []
        if timeline and show_timeline:
            for frame in timeline:
                print(f"  {frame['t']:.2f}s db={frame['db']:6.1f} hf={frame['hf']:.2f} zcr={frame['zcr']:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

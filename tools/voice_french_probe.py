"""Compréhension du français : 6 formulations réelles, mesurées, aucune supposition.

Méthode : on fait dire chaque phrase par une voix Gemini (audio réel), on renvoie
cet audio à Gemini Live (comme le ferait la WebSocket) et on compare la
transcription obtenue à la phrase d'origine (similarité de séquence).
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from pathlib import Path

from google import genai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.core.secrets import resolve_secret  # noqa: E402
from voice_languages_probe import hear, say, similarity  # noqa: E402

NUMBER_WORDS = (
    "un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|seize|"
    "vingt|trente|quarante|cinquante|soixante|cent|cents|mille|million|millions|milliard|milliards|"
    "dix-sept|dix-huit|dix-neuf"
)
import re  # noqa: E402

_NUMBER_RE = re.compile(rf"\b(?:\d+(?:[ .]\d+)*|(?:{NUMBER_WORDS})(?:[ -](?:{NUMBER_WORDS}))*)\b", re.I)


def normalize_numbers(text: str) -> str:
    """Remplace nombres en chiffres et en lettres par un jeton commun.

    Sans cela, « deux cent cinquante mille » face à « 250000 » est compté comme
    une erreur de compréhension alors que le sens est correct.
    """
    return _NUMBER_RE.sub(" NOMBRE ", text or "").lower()


PHRASES = [
    ("standard", "Bonjour Kwes, peux-tu me donner la météo de demain à Abidjan ?"),
    ("oral", "Euh, Kwes, dis-moi voir c'est quoi déjà le nom de ce truc là, le machin pour faire des recherches ?"),
    ("afrique-ouest", "Kwes, on dit quoi ? Trouve-moi les infos sur le prix du cacao cette semaine en Côte d'Ivoire."),
    ("imparfait", "moi vouloir savoir combien coûte un billet Abidjan Paris pour le mois prochain"),
    ("long", "Kwes, je prépare une réunion avec trois partenaires jeudi prochain, tu peux me faire un résumé des points importants et me dire quels documents je dois préparer avant ?"),
    ("chiffres", "Note bien : le budget est de deux cent cinquante mille francs CFA, et la livraison est prévue le quinze décembre."),
]


async def main() -> int:
    client = genai.Client(api_key=resolve_secret("GOOGLE_API_KEY"), http_options={"api_version": "v1beta"})
    results = []
    for label, phrase in PHRASES:
        pcm, _ = await say(client, phrase, "fr")
        if not pcm:
            results.append({"cas": label, "similarite": 0.0, "entendu": "", "erreur": "aucun audio"})
            print(f"{label:<14} audio=0 → échec")
            continue
        heard = await hear(client, pcm, "fr")
        score = similarity(phrase, heard)
        normalized = similarity(normalize_numbers(phrase), normalize_numbers(heard))
        results.append(
            {"cas": label, "similarite": round(score, 3), "similarite_normalisee": round(normalized, 3), "entendu": heard[:200]}
        )
        print(f"{label:<14} similarité={score:.3f} (normalisée={normalized:.3f}) · entendu : {heard[:80]}")

    average = statistics.mean([r["similarite"] for r in results])
    average_norm = statistics.mean([r["similarite_normalisee"] for r in results])
    summary = {
        "phrases": len(results),
        "similarite_moyenne": round(average, 3),
        "comprehension_pct": round(average * 100, 1),
        "comprehension_normalisee_pct": round(average_norm * 100, 1),
        "details": results,
    }
    (ROOT / ".probe" / "french_comprehension.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("phrases", "comprehension_pct", "comprehension_normalisee_pct")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

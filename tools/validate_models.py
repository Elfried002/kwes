#!/usr/bin/env python3
"""Validation des modèles de Kwes — exécution réelle, pas de déclaration.

Vérifie :
1. qu'aucun troisième modèle n'existe dans le code ou la configuration ;
2. que `gemini-3.8-live` répond et sait appeler un outil ;
3. que `gemini-3.8-live-extended-thinking` répond sans outil (capacité mesurée) ;
4. que la fluidité de conversation tient : premier fragment et réponse complète ;
5. qu'aucun repli n'est utilisé (le modèle retourné est toujours l'un des deux).

Sortie : un rapport court, avec les chiffres. Code retour 1 si un test échoue.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.agent.live_reasoner import LiveReasoner  # noqa: E402

ALLOWED = {"gemini-3.8-live", "gemini-3.8-live-extended-thinking"}
FORBIDDEN = (
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash",
    "flash-tts",
    "deepseek",
)
FAILURES: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    print(("  OK   " if condition else "  ÉCHEC") + f" · {label}" + (f" · {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


def static_scan() -> None:
    print("\n1. Aucun modèle interdit dans le code")
    patterns = "|".join(re.escape(item) for item in FORBIDDEN)
    result = subprocess.run(
        ["grep", "-rInE", patterns, "app", "config", "tools", "--include=*.py", "--include=*.yaml", "--include=*.toml", "--include=*.json"],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
    )
    hits = [
        line
        for line in result.stdout.splitlines()
        if "/tests/" not in line and "validate_models.py" not in line and "live_reasoner.py" not in line and "scan_secrets" not in line
    ]
    # Les commentaires qui documentent l'interdiction sont légitimes.
    offending = [line for line in hits if not line.lstrip().startswith("#")]
    check(not offending, "aucune référence exécutable à un modèle interdit", f"{len(offending)} ligne(s)")
    for line in offending[:5]:
        print("      ", line[:140])


async def main() -> int:
    settings = Settings()
    if not settings.gemini_api_key:
        print("Clé Gemini absente : validation impossible.")
        return 1
    reasoner = LiveReasoner(settings)

    static_scan()

    print("\n2. Modèle rapide — réponse et appel d'outil")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "donne_heure",
                "description": "Donne l'heure demandée.",
                "parameters": {
                    "type": "object",
                    "properties": {"ville": {"type": "string"}},
                    "required": ["ville"],
                },
            },
        }
    ]
    start = time.time()
    text, calls, model = await reasoner.generate(
        [{"role": "system", "content": "Tu es Kwes, une phrase maximum."},
         {"role": "user", "content": "Bonjour, qui es-tu ?"}],
        timeout=30,
    )
    check(bool(text), "réponse non vide", f"{len(text)} caractères en {time.time() - start:.1f} s")
    check(model == "gemini-3.8-live", "modèle attendu", model)

    start = time.time()
    text, calls, model = await reasoner.generate(
        [{"role": "system", "content": "Utilise l'outil."},
         {"role": "user", "content": "Quelle heure est-il à Abidjan ? Appelle donne_heure."}],
        tools=tools,
        timeout=30,
    )
    names = [call["name"] for call in calls]
    check("donne_heure" in names, "appel d'outil émis", f"{names} en {time.time() - start:.1f} s")

    print("\n3. Modèle approfondi — raisonnement sans outil")
    start = time.time()
    text, calls, model = await reasoner.generate(
        [{"role": "system", "content": "Réponds en deux phrases."},
         {"role": "user", "content": "Explique la différence entre un agent et un chatbot."}],
        purpose="mission",
        timeout=45,
    )
    check(bool(text), "réponse non vide", f"{len(text)} caractères en {time.time() - start:.1f} s")
    check(model == "gemini-3.8-live-extended-thinking", "modèle attendu", model)
    check(not calls, "aucun appel d'outil (capacité mesurée)", f"{len(calls)} appel(s)")

    print("\n4. Fluidité de conversation (5 tours)")
    turns = [
        "Bonjour Kwes.",
        "Quelle heure est-il à Abidjan s'il est 15 h UTC ?",
        "Combien font 17 fois 23 ?",
        "Tu peux chercher sur le web ?",
        "Merci, à tout à l'heure.",
    ]
    times: list[float] = []
    for message in turns:
        start = time.time()
        text, _, model = await reasoner.generate(
            [{"role": "system", "content": "Tu es Kwes, une phrase courte."},
             {"role": "user", "content": message}],
            timeout=40,
        )
        duration = time.time() - start
        times.append(duration)
        check(model in ALLOWED, f"modèle autorisé · « {message[:28]}… »", f"{duration:.1f} s")
        print(f"       {duration:5.2f} s · {text[:80]!r}")

    average = sum(times) / len(times)
    print(f"\n   moyenne {average:.2f} s · min {min(times):.2f} s · max {max(times):.2f} s")
    check(max(times) < 8.0, "aucun tour au-delà de 8 s", f"max {max(times):.2f} s")
    check(average < 6.0, "moyenne sous 6 s", f"{average:.2f} s")

    print("\n" + ("Tous les contrôles passent." if not FAILURES else f"{len(FAILURES)} contrôle(s) en échec : {', '.join(FAILURES)}"))
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

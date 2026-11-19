"""Vérification finale : recherche réelle + langue, en production."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = Path("/home/babayaga/business/kwes/.sb_bearer").read_text().strip()
BASE = "https://api.agent-kwes.com/api/v1"
HEAD = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

CASES = [
    ("fr", "Cherche qui a gagné la CAN 2025 et cite ta source."),
    ("en", "Search the web for the current price of cocoa and cite your source."),
]


def ask(question: str) -> tuple[int, dict, float]:
    request = urllib.request.Request(
        f"{BASE}/chat", method="POST", headers=HEAD,
        data=json.dumps({"message": question, "mode": "auto"}).encode(),
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read()), time.time() - started
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read()[:200].decode(errors="replace")}, time.time() - started


for langue, question in CASES:
    status, payload, duree = ask(question)
    texte = str(payload.get("response", ""))
    # Détection grossière de la langue de la réponse
    marqueurs_fr = ("le ", "la ", "les ", "est ", "pour ", "avec ", "source")
    marqueurs_en = (" the ", " is ", " and ", " with ", " source", " according")
    est_fr = sum(m in (" " + texte.lower() + " ") for m in marqueurs_fr)
    est_en = sum(m in (" " + texte.lower() + " ") for m in marqueurs_en)
    langue_repondue = "fr" if est_fr > est_en else "en"
    print(f"[{langue.upper()} demandé] HTTP {status} en {duree:.1f} s | langue répondue: {langue_repondue}")
    print("   →", texte[:230].replace("\n", " "))
    print()

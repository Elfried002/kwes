"""Recette de production : découverte du premier contact + rappel.

Ne contient aucun secret : le jeton est lu depuis .sb_bearer_verif (0600).
Écrit les tours dans /tmp/kwes_recette.json pour le rapport.
"""
import json
import pathlib
import time

import httpx

API = "https://api.agent-kwes.com/api/v1"
TOKEN = pathlib.Path(".sb_bearer_verif").read_text().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

TOURS = [
    "Bonjour",
    "Je m'appelle Kodjo",
    "Je dirige une petite entreprise de logistique à Cotonou",
    "Surtout m'aider à répondre à mes clients plus vite",
]

sortie = []
with httpx.Client(timeout=90) as client:
    conv = None
    for message in TOURS:
        payload = {"message": message}
        if conv:
            payload["conversation_id"] = conv
        started = time.monotonic()
        r = client.post(f"{API}/chat", json=payload, headers=HEADERS)
        r.raise_for_status()
        body = r.json()
        conv = body["conversation_id"]
        duree = round(time.monotonic() - started, 2)
        sortie.append({"tour": message, "reponse": body["response"], "secondes": duree})
        print(f"[{duree}s] U: {message}\n      A: {body['response']}\n")

    # Conversation neuve : seul le rappel mémoire peut fournir la réponse.
    started = time.monotonic()
    r = client.post(
        f"{API}/chat",
        json={"message": "Bonjour, quel est mon prénom et que fais-je ?"},
        headers=HEADERS,
    )
    r.raise_for_status()
    body = r.json()
    duree = round(time.monotonic() - started, 2)
    sortie.append({"conversation": "nouvelle", "tour": "rappel", "reponse": body["response"], "secondes": duree})
    print(f"[{duree}s] U: (nouvelle conversation) quel est mon prénom et que fais-je ?\n      A: {body['response']}\n")

    msgs = client.get(f"{API}/conversations/{body['conversation_id']}/messages", headers=HEADERS).json()
    sortie.append({"meta_conversation_neuve": [m["metadata"].get("discovery") for m in msgs]})
    print("metadata discovery (conversation neuve) :", [m["metadata"].get("discovery") for m in msgs])

pathlib.Path("/tmp/kwes_recette.json").write_text(json.dumps(sortie, ensure_ascii=False, indent=2))
print("saved /tmp/kwes_recette.json")

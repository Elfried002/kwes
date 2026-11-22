"""Recette de production du chemin réellement utilisé par l'interface.

L'écran de conversation appelle `/chat/stream` (SSE). Cette recette rejoue la
découverte du premier contact sur ce chemin et mesure le premier fragment.

Aucun secret affiché : le jeton vient de .sb_bearer_verif (0600).
"""
from __future__ import annotations

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


def tour(client: httpx.Client, message: str, conversation_id: str | None) -> dict:
    payload: dict = {"message": message, "mode": "auto"}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    debut = time.monotonic()
    premier = None
    texte: list[str] = []
    done: dict = {}
    with client.stream("POST", f"{API}/chat/stream", json=payload, headers=HEADERS) as reponse:
        reponse.raise_for_status()
        evenement = None
        for ligne in reponse.iter_lines():
            if ligne.startswith("event: "):
                evenement = ligne[7:]
            elif ligne.startswith("data: ") and evenement in {"delta", "done", "error"}:
                data = json.loads(ligne[6:])
                if evenement == "delta":
                    if premier is None:
                        premier = time.monotonic() - debut
                    texte.append(data.get("delta", ""))
                elif evenement == "done":
                    done = data
                elif evenement == "error":
                    raise SystemExit(f"erreur SSE: {data}")
    return {
        "tour": message,
        "reponse": "".join(texte).strip(),
        "premier_fragment_s": round(premier or 0, 2),
        "total_s": round(time.monotonic() - debut, 2),
        "conversation_id": done.get("conversation_id")
        or (payload.get("conversation_id")),
    }


resultats: list[dict] = []
with httpx.Client(timeout=120) as client:
    conv = None
    for message in TOURS:
        item = tour(client, message, conv)
        conv = item["conversation_id"]
        resultats.append(item)
        print(
            f"[1er fragment {item['premier_fragment_s']}s / total {item['total_s']}s] "
            f"U: {message}\n      A: {item['reponse']}\n"
        )

    rappel = tour(client, "Bonjour, quel est mon prénom et que fais-je ?", None)
    resultats.append(rappel)
    print(
        f"[1er fragment {rappel['premier_fragment_s']}s / total {rappel['total_s']}s] "
        f"U: (nouvelle conversation) quel est mon prénom et que fais-je ?\n"
        f"      A: {rappel['reponse']}\n"
    )

    msgs = client.get(
        f"{API}/conversations/{rappel['conversation_id']}/messages", headers=HEADERS
    ).json()
    resultats.append({"meta_conversation_neuve": [m["metadata"].get("discovery") for m in msgs]})
    print("metadata discovery (conversation neuve) :", [m["metadata"].get("discovery") for m in msgs])

pathlib.Path("/tmp/kwes_recette_stream.json").write_text(
    json.dumps(resultats, ensure_ascii=False, indent=2)
)
print("saved /tmp/kwes_recette_stream.json")

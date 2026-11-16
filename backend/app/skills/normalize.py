"""Normalisation des entrées de skills avant validation.

Un plan produit par le LLM peut employer un synonyme là où le schéma attend une
valeur d'énumération (« approfondie » au lieu de « deep »). Sans normalisation,
la mission échoue sur une erreur de validation qui n'a rien à voir avec une
panne : constaté le 16/11 sur une mission réelle (`depth: "approfondie"`).

La normalisation reste volontairement étroite : elle ne devine rien, elle
n'accepte que des synonymes explicitement listés.
"""

from __future__ import annotations

from typing import Any

DEPTH_ALIASES: dict[str, str] = {
    "quick": "quick",
    "rapide": "quick",
    "court": "quick",
    "standard": "standard",
    "normal": "standard",
    "moyen": "standard",
    "deep": "deep",
    "approfondi": "deep",
    "approfondie": "deep",
    "complet": "deep",
    "complète": "deep",
    "complete": "deep",
}


def normalize_payload(skill: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Renvoie une copie corrigée du payload pour les cas connus."""
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    if skill == "web_research":
        depth = normalized.get("depth")
        if isinstance(depth, str):
            normalized["depth"] = DEPTH_ALIASES.get(
                depth.strip().lower(), DEPTH_ALIASES.get(depth.strip(), "standard")
            )
    return normalized

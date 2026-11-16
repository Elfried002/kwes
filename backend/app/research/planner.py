"""Query Planner : transforme une demande en quelques requêtes utiles.

Volontairement déterministe (aucun appel LLM en P1) : le plan est prévisible,
testable et sans coût. Les variantes restent proches de la demande d'origine —
on ne remplace jamais silencieusement une requête par une autre.
"""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    {"le", "la", "les", "de", "des", "du", "un", "une", "et", "en", "au", "aux", "pour", "sur", "dans", "avec", "que", "qui"}
)

# Suffixes utiles par profondeur : ils orientent vers des sources exploitables.
VARIANTS = {
    "quick": ("",),
    "standard": ("", "analyse"),
    "deep": ("", "rapport officiel", "données chiffres", "actualité"),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def plan_queries(query: str, depth: str = "standard", max_queries: int = 4) -> list[str]:
    base = _norm(query)
    if not base:
        return []
    depth = depth if depth in VARIANTS else "standard"
    planned: list[str] = []
    for suffix in VARIANTS[depth]:
        candidate = base if not suffix else f"{base} {suffix}"
        if candidate.lower() not in {item.lower() for item in planned}:
            planned.append(candidate)
        if len(planned) >= max_queries:
            break
    return planned[:max_queries]


def key_terms(query: str, limit: int = 8) -> list[str]:
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) > 3 and t not in STOPWORDS]
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    return seen[:limit]

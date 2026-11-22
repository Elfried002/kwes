"""Apprentissage progressif : extraction et persistance des faits durables.

À chaque tour, ce que l'utilisateur énonce de durable sur lui-même (prénom,
activité, projets, préférences, contraintes, objectifs, langue de travail) est
enregistré sans qu'il ait à le demander.

Trois exigences, tenues ici et vérifiées par les tests :

* **non bloquant** : extraction par règles, sans appel modèle (quelques
  microsecondes) ; la seule dépense est une lecture et une écriture SQL ;
* **dédupliqué** : un même sujet (« Prénom ») met à jour la ligne existante au
  lieu d'en créer une douzième ; un contenu identique n'est jamais réinséré ;
* **sans données sensibles** : un message qui contient un mot de passe, un
  numéro de carte, un jeton ou une clé d'API n'est jamais mémorisé.

Le scoping est celui de la base : `user_id` est toujours celui de l'auteur du
message, et `tenant_id` est estampillé par le contexte de requête
(`before_flush`). Un fait ne peut donc pas atterrir dans la mémoire d'autrui.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory

MAX_VALUE_CHARS = 160
MAX_FACT_CHARS = 500

#: Marqueurs de secret : un message qui en contient un n'est pas mémorisé.
#: Volontairement large — mieux vaut perdre un fait que stocker un jeton.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:mot\s*de\s*passe|password|passwd|pwd|code\s*secret)\b", re.IGNORECASE),
    re.compile(r"\b(?:num[eé]ro\s+de\s+carte|carte\s+bancaire|cvv|cvc|code\s+de\s+validation)\b", re.IGNORECASE),
    re.compile(r"\b(?:jeton|token|api[_\s-]?key|cl[ée]\s+(?:d'?api|priv[ée]e)|secret)\b", re.IGNORECASE),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),  # numéro de carte
    re.compile(r"\b(?:sk-|pk-|ghp_|gho_|xox[bap]-|AKIA)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"\bIBAN\b|\bFR\d{2}[ ]?\d{4}", re.IGNORECASE),
)

#: Demandes explicites de mémorisation : dans ce cas c'est l'outil `remember`
#: qui écrit (le modèle reformule mieux que nos règles), et l'extraction
#: automatique se tait pour ne pas créer une seconde ligne pour le même fait.
_EXPLICIT_REMEMBER = re.compile(
    r"\b(?:retiens|retiens[- ]le|m[eé]morise|souviens[- ]toi|n['’]oublie\s+pas|"
    r"garde\s+en\s+m[eé]moire|remember\s+that|keep\s+in\s+mind)\b",
    re.IGNORECASE,
)

_NAME_STOPWORDS = {
    "desole", "désolé", "ici", "ok", "oui", "non", "pas", "sur", "sure", "content",
    "contente", "ravi", "ravie", "fatigue", "fatigué", "disponible", "pret", "prêt",
    "en", "de", "retour", "daccord", "d'accord", "bonjour", "salut", "hello",
}

#: Mots qui terminent un prénom : sans cette coupure, « je m'appelle Awa et je
#: dirige… » stockait toute la phrase comme prénom (constaté en test).
_NAME_BREAKS = _NAME_STOPWORDS | {
    "et", "je", "j", "tu", "il", "elle", "nous", "vous", "ils", "elles",
    "mon", "ma", "mes", "ton", "ta", "tes", "qui", "que", "dont", "car", "mais",
    "donc", "puis", "travaille", "dirige", "suis", "fais", "habite", "vis",
    "and", "i", "my", "who", "work", "run", "live",
}

#: Libellé lisible du sujet, en tête de la ligne de mémoire. Sert aussi de clé
#: de déduplication : « Prénom : Elfried » met à jour « Prénom : ... ».
LABELS: dict[str, str] = {
    "nom": "Prénom",
    "activite": "Activité",
    "priorite": "Objectif prioritaire",
    "langue": "Langue de travail",
    "preference": "Préférence",
    "projet": "Projet",
    "contrainte": "Contrainte",
}

CATEGORY_BY_KEY: dict[str, str] = {
    "nom": "semantic",
    "activite": "semantic",
    "priorite": "semantic",
    "langue": "semantic",
    "preference": "semantic",
    "projet": "working",
    "contrainte": "semantic",
}

SENSITIVITY_BY_KEY: dict[str, str] = {
    "nom": "personal",
}


@dataclass(frozen=True)
class Fact:
    """Un fait durable, prêt à être écrit."""
    key: str
    content: str
    category: str
    sensitivity: str = "normal"

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key)


def _strip_accents(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def contains_secret(text: str) -> bool:
    """Vrai si le message ressemble à un secret : jamais mémorisé."""
    return any(pattern.search(text or "") for pattern in _SECRET_PATTERNS)


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip(" \t\n\r\"'«»“”")
    value = re.split(r"[.;!?]\s|[.;!?]$", value, maxsplit=1)[0].strip()
    value = value.strip(" ,:;-–—")
    if len(value) > MAX_VALUE_CHARS:
        value = value[:MAX_VALUE_CHARS].rstrip() + "…"
    return value


def _name_candidate(value: str) -> str:
    """Ne garde que les premiers mots d'un prénom/nom propre."""
    kept: list[str] = []
    for word in value.split():
        if _strip_accents(word).strip(".,;:!?").lower() in _NAME_BREAKS:
            break
        kept.append(word)
        if len(kept) == 3:
            break
    return " ".join(kept)


def _valid_name(value: str) -> bool:
    words = value.split()
    if not (1 <= len(words) <= 3):
        return False
    if any(_strip_accents(word).lower() in _NAME_STOPWORDS for word in words):
        return False
    return bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’\- ]{2,40}", value))


def _titlecase_name(value: str) -> str:
    parts = []
    for word in value.split():
        parts.append(word[:1].upper() + word[1:] if word.islower() else word)
    return " ".join(parts)


def _first(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _clean(match.group(1))
            if len(value) >= 2:
                return value
    return None


def _extract_name(text: str, discovery_topic: str | None) -> str | None:
    value = _first(
        text,
        (
            r"\bje m['’]appelle\s+([^\n,]{2,40})",
            r"\bmoi,?\s+c['’]est\s+([A-Za-zÀ-ÿ'’\-]{2,30})",
            r"\bmon\s+nom\s+(?:est|c['’]est)\s+([^\n,]{2,40})",
            r"\bappelle[- ]moi\s+([^\n,]{2,40})",
            r"\bmy\s+name\s+is\s+([^\n,]{2,40})",
            r"\bcall\s+me\s+([^\n,]{2,40})",
        ),
    )
    if value is None and discovery_topic == "nom":
        # Réponse courte à « comment souhaitez-vous que je vous appelle ? » :
        # une personne répond « Elfried », pas « je m'appelle Elfried ».
        candidate = _clean(text)
        if _valid_name(candidate) and len(candidate.split()) <= 4:
            value = candidate
    if value is None:
        return None
    value = _titlecase_name(_name_candidate(value))
    return value if _valid_name(value) else None


def _extract_activity(text: str) -> str | None:
    return _first(
        text,
        (
            r"\bje\s+travaille\s+(?:dans|chez|pour|comme)\s+([^\n,]{3,120})",
            r"\bje\s+(?:dirige|g[eè]re|fonde|pr[eé]side|manage)\s+(?!que\b)([^\n,]{3,120})",
            r"\b(?:mon|notre)\s+(?:activit[eé]|m[eé]tier|entreprise|soci[eé]t[eé]|bo[iî]te|business)\s*(?:est|c['’]est|:)?\s*([^\n,]{3,120})",
            r"\bje\s+suis\s+(?:un |une )?(?:d[eé]veloppeu?r(?:se)?|fondat(?:eur|rice)|entrepreneu?r(?:se)?|consultant[e]?|commer[cç]ant[e]?|[eé]tudiant[e]?|freelance|ind[eé]pendant[e]?|g[eé]rant[e]?|direct(?:eur|rice)|chef d['’]entreprise|artisan[e]?|agriculteu?r(?:rice)?)\b([^\n,]{0,80})",
            r"\bi\s+(?:run|own|founded|manage)\s+([^\n,]{3,120})",
            r"\bi\s+work\s+(?:at|for|in|as)\s+([^\n,]{3,120})",
        ),
    )


def _extract_priority(text: str) -> str | None:
    return _first(
        text,
        (
            r"\bj['’]attends\s+(?:de\s+(?:toi|vous)|que\s+(?:tu|vous))\s+([^\n,]{3,140})",
            r"\bj['’]ai\s+besoin\s+(?:de\s+(?:toi|vous)|que\s+(?:tu|vous))\s+([^\n,]{3,140})",
            r"\bce\s+que\s+je\s+veux,?\s+c['’]est\s+([^\n,]{3,140})",
            r"\b(?:mon|ma)\s+(?:objectif|priorit[eé]|but)\s*(?:est|c['’]est|:)?\s*([^\n,]{3,140})",
            r"\bi\s+need\s+(?:you\s+)?to\s+([^\n,]{3,140})",
            r"\bmy\s+(?:goal|priority)\s+is\s+([^\n,]{3,140})",
        ),
    )


def _extract_language(text: str) -> str | None:
    value = _first(
        text,
        (
            r"\bje\s+travaille\s+(?:en|dans\s+le|dans\s+l['’])\s*(fran[cç]ais|anglais|english|french|espagnol|allemand)",
            r"\b(?:r[eé]ponds|parle)[- ]moi?\s+(?:en|in)\s+(fran[cç]ais|anglais|english|french)",
            r"\bma\s+langue\s+(?:de\s+travail\s+)?est\s+(?:le\s+|l['’])?(fran[cç]ais|anglais|english|french|espagnol|allemand)",
            r"\bi\s+work\s+in\s+(english|french|spanish|german)",
        ),
    )
    if value is None:
        return None
    normalise = {
        "francais": "français",
        "français": "français",
        "french": "français",
        "anglais": "anglais",
        "english": "anglais",
        "espagnol": "espagnol",
        "spanish": "espagnol",
        "allemand": "allemand",
        "german": "allemand",
    }
    return normalise.get(_strip_accents(value).lower(), value)


def _extract_preference(text: str) -> str | None:
    return _first(
        text,
        (
            r"\bje\s+pr[eé]f[eè]re\s+([^\n,]{3,120})",
            r"\bj['’]aime\s+(?:bien\s+)?(?:quand\s+|travailler\s+|les?\s+|la\s+|le\s+)?([^\n,]{3,120})",
            r"\bje\s+n['’]aime\s+pas\s+([^\n,]{3,120})",
            r"\bi\s+prefer\s+([^\n,]{3,120})",
        ),
    )


def _extract_project(text: str) -> str | None:
    return _first(
        text,
        (
            r"\bje\s+(?:travaille\s+sur|d[eé]veloppe|lance|pr[eé]pare|construis)\s+([^\n,]{3,120})",
            r"\b(?:mon|notre)\s+projet\s*(?:est|c['’]est|:)?\s*([^\n,]{3,120})",
            r"\bi\s+(?:am\s+building|build|am\s+working\s+on|launched)\s+([^\n,]{3,120})",
        ),
    )


def _extract_constraint(text: str) -> str | None:
    return _first(
        text,
        (
            r"\bje\s+ne\s+peux\s+pas\s+([^\n,]{3,120})",
            r"\bje\s+dois\s+([^\n,]{3,120})",
            r"\bi\s+can['’]t\s+([^\n,]{3,120})",
        ),
    )


def _short_answer(value: str) -> str | None:
    """Réponse courte à une question de découverte (« surtout… », « je fais… »)."""
    cleaned = _clean(value)
    cleaned = re.sub(
        r"^(?:surtout|plut[oô]t|en fait|bah|ben|et bien|euh)\s+", "", cleaned, flags=re.IGNORECASE
    )
    if len(cleaned) < 3 or len(cleaned) > 160 or cleaned.endswith("?"):
        return None
    if _strip_accents(cleaned).lower() in {
        "merci", "ok", "d'accord", "daccord", "oui", "non", "rien", "aucune idée",
        "je ne sais pas", "sais pas", "comme tu veux", "peu importe",
        "bonjour", "bonsoir", "salut", "hello", "ca va", "ça va",
        "comment vas-tu", "comment vas tu", "comment allez-vous",
    }:
        return None
    return cleaned


def extract_facts(text: str, *, discovery_topic: str | None = None) -> list[Fact]:
    """Extrait les faits durables d'un message. Aucune écriture ici.

    `discovery_topic` indique la question de découverte posée au tour précédent,
    ce qui permet d'interpréter une réponse courte (« Elfried », « surtout
    répondre aux clients ») comme un prénom, une activité ou une priorité.
    """
    raw = (text or "").strip()
    if len(raw) < 2 or len(raw) > 4000:
        return []
    if contains_secret(raw):
        return []
    if _EXPLICIT_REMEMBER.search(raw):
        # « Retiens que… » / « mémorise… » : l'outil `remember` s'en charge,
        # avec une reformulation de meilleure qualité que nos règles.
        return []

    found: dict[str, str] = {}
    nom = _extract_name(raw, discovery_topic)
    if nom:
        found["nom"] = nom
    activite = _extract_activity(raw)
    if activite:
        found["activite"] = activite
    priorite = _extract_priority(raw)
    if priorite:
        found["priorite"] = priorite
    langue = _extract_language(raw)
    if langue:
        found["langue"] = langue
    preference = _extract_preference(raw)
    if preference:
        found["preference"] = preference
    projet = _extract_project(raw)
    if projet:
        found["projet"] = projet
    contrainte = _extract_constraint(raw)
    if contrainte:
        found["contrainte"] = contrainte

    # Réponse directe à une question de découverte : la règle explicite n'a pas
    # matché et aucun autre fait n'a été trouvé, mais la personne répond bien au
    # sujet demandé. Sans cette condition, « je préfère… » deviendrait une
    # activité au tour suivant.
    if not found and discovery_topic in {"activite", "priorite"}:
        answer = _short_answer(raw)
        if answer:
            found[discovery_topic] = answer

    facts: list[Fact] = []
    for key, value in found.items():
        content = f"{LABELS[key]} : {value}"
        if len(content) > MAX_FACT_CHARS:
            continue
        facts.append(
            Fact(
                key=key,
                content=content,
                category=CATEGORY_BY_KEY.get(key, "semantic"),
                sensitivity=SENSITIVITY_BY_KEY.get(key, "normal"),
            )
        )
    return facts


def fact_label(content: str) -> str | None:
    """Libellé (« Prénom ») d'une ligne de mémoire, pour la déduplication."""
    if " : " not in (content or ""):
        return None
    label = content.split(" : ", 1)[0].strip()
    return label.casefold() or None


def _normalise(content: str) -> str:
    return re.sub(r"\s+", " ", (content or "")).strip().casefold()


async def persist_facts(
    session: AsyncSession, *, user_id: uuid.UUID, facts: list[Fact]
) -> list[Fact]:
    """Écrit les faits en mettant à jour les sujets déjà connus.

    Retourne uniquement les faits réellement créés ou modifiés (un fait déjà
    présent à l'identique est ignoré : pas de doublon, pas d'écriture inutile).
    """
    if not facts:
        return []

    rows = (
        await session.execute(
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.updated_at.desc())
            .limit(500)
        )
    ).scalars().all()

    by_label: dict[str, Memory] = {}
    known_contents: set[str] = set()
    for row in rows:
        label = fact_label(row.content)
        if label and label not in by_label:
            by_label[label] = row
        known_contents.add(_normalise(row.content))

    written: list[Fact] = []
    for fact in facts:
        existing = by_label.get(fact.label.casefold())
        if existing is not None:
            if _normalise(existing.content) == _normalise(fact.content):
                continue
            existing.content = fact.content
            existing.category = fact.category
            existing.sensitivity = fact.sensitivity
            known_contents.add(_normalise(fact.content))
            written.append(fact)
            continue
        if _normalise(fact.content) in known_contents:
            continue
        row = Memory(
            user_id=user_id,
            category=fact.category,
            content=fact.content,
            source_type="agent",
            confidence=0.9,
            sensitivity=fact.sensitivity,
        )
        session.add(row)
        by_label[fact.label.casefold()] = row
        known_contents.add(_normalise(fact.content))
        written.append(fact)

    if written:
        await session.flush()
    return written

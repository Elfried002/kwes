"""Briques de base du moteur de recherche : URL, déduplication, qualité de source.

Aucune de ces fonctions n'appelle le réseau : elles sont testables isolément.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
        "gclid", "dclid", "fbclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid",
        "ref", "ref_src", "referrer", "source", "spm", "share", "share_id", "_ga",
    }
)
DEFAULT_PORTS = {"http": 80, "https": 443}

OFFICIAL_SUFFIXES = (".gov", ".gouv", ".gouv.ci", ".gov.uk", ".int", ".europa.eu", ".un.org", ".edu")
MEDIA_DOMAINS = frozenset(
    {
        "lemonde.fr", "lefigaro.fr", "lesechos.fr", "jeuneafrique.com", "rfi.fr", "bbc.com",
        "bbc.co.uk", "reuters.com", "bloomberg.com", "ft.com", "nytimes.com", "theguardian.com",
        "abidjan.net", "fr.africanews.com", "africanews.com", "france24.com", "dw.com",
    }
)
COMMUNITY_DOMAINS = frozenset(
    {
        "reddit.com", "stackoverflow.com", "stackexchange.com", "quora.com", "news.ycombinator.com",
        "github.com", "gitlab.com", "forum.", "discourse.",
    }
)


@dataclass(slots=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    provider: str
    rank: int = 0
    published_at: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Source:
    url: str
    canonical_url: str
    domain: str
    title: str
    snippet: str
    providers: list[str] = field(default_factory=list)
    category: str = "inconnue"
    score: float = 0.0
    excerpt: str | None = None
    evidence_id: str | None = None
    status: str = "trouvée"


@dataclass(slots=True)
class ResearchOutcome:
    answer: str
    sources: list[Source]
    queries: list[str]
    providers_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cached: bool = False
    evidence_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------
def domain_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def canonicalize_url(url: str) -> str:
    """Normalise une URL : schéma, hôte, port, paramètres de suivi, fragment.

    Ne supprime jamais un paramètre inconnu : seul le suivi publicitaire est
    retiré, pour ne pas fusionner deux pages réellement différentes.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host
    if port and DEFAULT_PORTS.get(scheme) != port:
        netloc = f"{host}:{port}"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def is_pdf_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


# ---------------------------------------------------------------------------
# Qualité de source
# ---------------------------------------------------------------------------
def classify_source(domain: str) -> str:
    """Classe un domaine sans confondre popularité et fiabilité."""
    if not domain:
        return "inconnue"
    if domain.endswith(OFFICIAL_SUFFIXES) or ".gouv." in domain or domain.startswith("gov."):
        return "officielle"
    if domain in MEDIA_DOMAINS or any(domain.endswith("." + d) for d in MEDIA_DOMAINS):
        return "média"
    if domain in COMMUNITY_DOMAINS or any(token in domain for token in ("forum.", "discourse.")):
        return "communauté"
    if domain.endswith(".org"):
        return "organisation"
    return "inconnue"


CATEGORY_WEIGHT = {
    "officielle": 3.0,
    "organisation": 2.0,
    "média": 1.6,
    "inconnue": 1.0,
    "communauté": 0.6,
}


def score_source(source: Source, query: str, rank: int = 0) -> float:
    """Score expliquant le classement : catégorie, accord des fournisseurs, pertinence."""
    weight = CATEGORY_WEIGHT.get(source.category, 1.0)
    agreement = min(len(source.providers), 3) * 0.4
    position = max(0.0, 1.0 - rank * 0.08)
    terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 3]
    haystack = f"{source.title} {source.snippet}".lower()
    relevance = sum(1 for term in terms if term in haystack) / max(1, len(terms))
    return round(weight + agreement + position + relevance * 1.2, 3)


# ---------------------------------------------------------------------------
# Sélection de passage
# ---------------------------------------------------------------------------
def best_passage(text: str, *, min_chars: int = 200, max_chars: int = 700) -> str:
    """Choisit le premier bloc de texte ressemblant à de la prose.

    Les pages réelles commencent souvent par des menus, des listes de langues ou
    des barres de navigation : prendre les 400 premiers caractères produit un
    extrait inutilisable (constaté sur Wikipédia). On ignore les blocs faits de
    lignes très courtes et on garde le premier paragraphe substantiel.
    """
    if not text:
        return ""
    blocks = re.split(r"\n\s*\n|(?<=\.)\s{2,}", text)
    best = ""
    for block in blocks:
        cleaned = re.sub(r"\s+", " ", block).strip()
        if len(cleaned) < min_chars:
            continue
        # Proportion de « lignes courtes » : signal fort d'un menu ou d'une liste.
        short = sum(1 for token in cleaned.split(" ") if len(token) <= 3)
        if short / max(1, len(cleaned.split(" "))) > 0.45:
            continue
        words = cleaned.split(" ")
        avg_word = sum(len(w) for w in words) / max(1, len(words))
        if avg_word < 3.2:
            continue
        best = cleaned
        break
    if not best:
        best = re.sub(r"\s+", " ", text).strip()
    if len(best) > max_chars:
        cut = best[:max_chars]
        for separator in (". ", "! ", "? "):
            index = cut.rfind(separator)
            if index > max_chars * 0.5:
                return cut[: index + 1]
        return cut.rstrip() + "…"
    return best


# ---------------------------------------------------------------------------
# Déduplication
# ---------------------------------------------------------------------------
def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:60]


def dedupe_hits(hits: list[SearchHit]) -> list[Source]:
    """Fusionne les doublons d'URL et de titre en conservant toutes les provenances."""
    merged: dict[str, Source] = {}
    titles: dict[str, str] = {}
    for hit in hits:
        canonical = canonicalize_url(hit.url)
        if not canonical.startswith("http"):
            continue
        key = canonical
        title_key = _title_key(hit.title)
        # Même titre, même domaine : très probablement la même page.
        if title_key and title_key in titles:
            key = titles[title_key]
        existing = merged.get(key)
        if existing is None:
            merged[key] = Source(
                url=hit.url,
                canonical_url=canonical,
                domain=domain_of(canonical),
                title=hit.title.strip()[:500] or canonical,
                snippet=hit.snippet.strip()[:400],
                providers=[hit.provider],
                category=classify_source(domain_of(canonical)),
            )
            if title_key:
                titles[title_key] = key
        else:
            if hit.provider not in existing.providers:
                existing.providers.append(hit.provider)
            # On garde l'extrait le plus long : il contient généralement plus d'information.
            if len(hit.snippet) > len(existing.snippet):
                existing.snippet = hit.snippet.strip()[:400]
    return list(merged.values())

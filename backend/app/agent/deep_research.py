"""Recherche approfondie multi-sources : plusieurs requêtes, plusieurs pages lues, synthèse citée.

Ce parcours est explicite (`mode="recherche"`) ou déclenché par une demande
formulée comme telle (« recherche approfondie », « multi-sources », « compare
plusieurs sources »). Il exécute un vrai travail en plusieurs étapes :

1. planification de 3 à 5 requêtes (variantes déterministes de la demande) ;
2. exécution réelle des requêtes sur le routeur de recherche (SearXNG local,
   puis DuckDuckGo, puis Wikipédia) ;
3. lecture des 3 à 5 meilleures pages et extraction du texte lisible ;
4. synthèse par DeepSeek, chaque affirmation devant porter la citation du
   numéro de la source réellement lue.

Aucune source n'est inventée : une page qui échoue est retirée de la synthèse et
nommée dans les limites. Si aucune page n'a pu être lue, aucune synthèse n'est
rédigée — le résultat le dit.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

from app.agent.llm import LLMClient, LLMError, LLMResult
from app.core.config import Settings
from app.research.core import SearchHit, Source, best_passage, dedupe_hits, score_source
from app.research.extract import extract_pdf, looks_like_pdf
from app.research.planner import key_terms
from app.research.providers import ResearchCache, build_router
from app.skills.base import FetchFn
from app.skills.fetch import extract_readable, sanitize_text, validate_url_shape

logger = logging.getLogger("kwes.deep_research")

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")

SearchFn = Callable[[str], Awaitable[list[SearchHit]]]

# Une question complète (« Quel est le niveau actuel du prix… et quels sont les
# facteurs… ») donne des requêtes que les moteurs interprètent mal : mesuré en
# production, SearXNG renvoyait la page du mot « quel » dans le Wiktionnaire.
# On repart du sujet, débarrassé de l'interrogation et de la seconde proposition.
_QUESTION_PREFIXES = (
    "quel est ", "quelle est ", "quels sont ", "quelles sont ", "combien ",
    "comment ", "pourquoi ", "quand ", "où ", "que sont ",
    "what is ", "what are ", "how much ", "how many ", "why ", "when ",
    "where ", "who is ", "which ",
)
_SECOND_CLAUSE = (
    " et quels", " et quelles", " et pourquoi", " et comment", " et quand",
    " ainsi que", " and what", " and why", " and how",
)
# L'instruction elle-même n'est pas un mot-clé de recherche : la garder produit
# des requêtes du type « Fais une recherche approfondie sur … » qui ramènent des
# pages hors sujet. On retire la consigne, on garde le sujet.
_WORK_INSTRUCTION_PREFIXES = tuple(
    sorted(
        (
            "fais-moi une recherche approfondie sur", "fais-moi une recherche sur",
            "fais une recherche approfondie sur", "fais une recherche approfondie de",
            "fais une recherche approfondie", "fais une recherche sur",
            "fais une recherche de", "recherche approfondie sur", "recherche approfondie de",
            "recherche approfondie", "cherche des informations sur", "trouve des informations sur",
            "documente-toi sur", "recherche multi-sources sur", "recherche multi-source sur",
            "compare plusieurs sources sur", "recherche sur", "cherche sur", "cherche ",
            "trouve ", "compare ", "analyse ",
            "do a deep research on", "deep research on", "find information about",
            "research ", "look up ",
        ),
        key=len,
        reverse=True,
    )
)
_DEEP_SUFFIXES_FR = ("rapport officiel", "données chiffres", "actualité")
_DEEP_SUFFIXES_EN = ("official report", "data figures", "latest news")


def plan_deep_queries(question: str, *, language: str = "fr", count: int = 4) -> list[str]:
    """3 à 5 requêtes dérivées du sujet réel de la question, sans la reformuler."""
    english = str(language).lower().startswith("en")
    base = re.sub(r"\s+", " ", question or "").strip()
    lowered = base.lower()
    for prefix in _QUESTION_PREFIXES:
        if lowered.startswith(prefix):
            base = base[len(prefix):]
            lowered = base.lower()
            break
    for separator in _SECOND_CLAUSE:
        index = lowered.find(separator)
        if index > 12:
            base = base[:index]
            lowered = base.lower()
            break
    base = base.strip(" ?.!,;:")
    for instruction in _WORK_INSTRUCTION_PREFIXES:
        if base.lower().startswith(instruction):
            stripped = base[len(instruction):].strip(" ?.!,;:")
            if len(stripped) >= 4:
                base = stripped
            break
    for article in ("le ", "la ", "les ", "l'", "the ", "a ", "an "):
        if base.lower().startswith(article):
            base = base[len(article):]
            break
    words = base.split(" ")
    if len(words) > 12:
        base = " ".join(words[:12])
    suffixes = _DEEP_SUFFIXES_EN if english else _DEEP_SUFFIXES_FR
    planned: list[str] = []
    for suffix in ("", *suffixes):
        candidate = base if not suffix else f"{base} {suffix}"
        if candidate.strip() and candidate.strip().lower() not in {p.lower() for p in planned}:
            planned.append(candidate.strip())
        if len(planned) >= max(3, count):
            break
    return planned[: max(3, count)]

SYSTEM_PROMPT_FR = """Tu rédiges la synthèse d'une recherche approfondie pour Kwes.

Règles absolues :
- Utilise UNIQUEMENT les extraits fournis. Aucun fait, chiffre, date ou nom qui n'y figure.
- Chaque affirmation factuelle porte une citation [n] correspondant au numéro de l'extrait.
- Si deux extraits se contredisent, dis-le. Si une information demandée manque, dis-le.
- Un extrait marqué ILLISIBLE ne doit pas être utilisé : mentionne-le dans « Limites ».
- N'invente jamais une source, une URL ou une citation.

Structure attendue, sans préambule :
1. Deux ou trois phrases de réponse directe.
2. « Ce que disent les sources » : 3 à 6 puces, chacune terminée par [n].
3. « Limites » : ce qui n'a pas pu être vérifié ou lu."""

SYSTEM_PROMPT_EN = """You write the synthesis of a deep research run for Kwes.

Absolute rules:
- Use ONLY the provided excerpts. No fact, figure, date or name that is not in them.
- Every factual claim carries a citation [n] matching the excerpt number.
- If excerpts contradict each other, say so. If requested information is missing, say so.
- An excerpt marked UNREADABLE must not be used; mention it under "Limits".
- Never invent a source, a URL or a quotation.

Expected structure, no preamble:
1. Two or three sentences answering directly.
2. "What the sources say": 3 to 6 bullets, each ending with [n].
3. "Limits": what could not be verified or read."""


@dataclass
class ReadSource:
    url: str
    title: str
    domain: str
    status: str  # lue | illisible | vide | refusee
    chars: int = 0
    text: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "domain": self.domain,
            "status": self.status,
            "chars": self.chars,
            **({"note": self.note} if self.note else {}),
        }


@dataclass
class DeepResearchResult:
    answer: str
    sources: list[ReadSource] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    citations: list[int] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str | None = None

    @property
    def read_count(self) -> int:
        return sum(1 for s in self.sources if s.status == "lue")

    @property
    def cited_count(self) -> int:
        return len(self.citations)

    def meta(self) -> dict[str, Any]:
        """Métadonnées exposées dans la réponse (aucun contenu de page)."""
        return {
            "queries": list(self.queries),
            "sources": [s.as_dict() for s in self.sources],
            "sources_read": self.read_count,
            "sources_cited": self.cited_count,
            "citations": list(self.citations),
            "providers": list(self.providers),
            "model": self.model,
            "elapsed_ms": self.elapsed_ms,
            "usage": dict(self.usage),
            "warnings": list(self.warnings),
            **({"error": self.error} if self.error else {}),
        }


class DeepResearchRunner:
    """Parcours de recherche approfondie : recherche réelle, lecture réelle, synthèse citée."""

    def __init__(
        self,
        settings: Settings,
        *,
        llm: LLMClient | None = None,
        fetcher: FetchFn | None = None,
        search: SearchFn | None = None,
    ) -> None:
        self.settings = settings
        self._llm = llm
        self._fetcher = fetcher
        self._search_fn = search

    # -- dépendances -----------------------------------------------------
    @property
    def llm(self) -> LLMClient | None:
        if self._llm is None and self.settings.deepseek_available:
            from app.agent.deepseek_text import DeepSeekTextClient

            self._llm = DeepSeekTextClient(self.settings)
        return self._llm

    @property
    def available(self) -> bool:
        return bool(self.settings.deep_research_max_pages) and (
            self._llm is not None or self.settings.deepseek_available
        )

    def _make_fetcher(self) -> FetchFn:
        if self._fetcher is not None:
            return self._fetcher
        from app.skills.fetch import make_fetcher

        self._fetcher = make_fetcher(self.settings.browser_domain_allowlist, self.settings)
        return self._fetcher

    # -- recherche --------------------------------------------------------
    async def _search(self, queries: Sequence[str], language: str) -> tuple[list[SearchHit], list[str], list[str]]:
        if self._search_fn is not None:
            collected: list[SearchHit] = []
            for query in queries:
                try:
                    collected.extend(await self._search_fn(query))
                except Exception as exc:  # noqa: BLE001 — une requête en échec n'arrête pas tout
                    logger.warning("Recherche approfondie : requête en échec (%s)", type(exc).__name__)
            return collected, [], []

        router, client = await build_router(
            searxng_url=self.settings.searxng_url,
            cache=ResearchCache(None, enabled=False),
            daily_limit=self.settings.research_provider_daily_limit,
        )
        try:
            gathered = await asyncio.gather(
                *(router.search(query, limit=8, language=language) for query in queries),
                return_exceptions=True,
            )
        finally:
            await client.aclose()

        hits: list[SearchHit] = []
        providers: list[str] = []
        warnings: list[str] = []
        for query, item in zip(queries, gathered):
            if isinstance(item, BaseException):
                warnings.append(f"Requête « {query[:60]} » en échec ({type(item).__name__}).")
                continue
            results, used, notes = item
            hits.extend(results)
            providers.extend(p for p in used if p not in providers)
            warnings.extend(n for n in notes if n not in warnings)
        return hits, providers, warnings

    def _select_sources(self, hits: Sequence[SearchHit], query: str) -> list[Source]:
        """Déduplique, score, puis écarte les résultats hors sujet.

        Un moteur renvoie parfois une page sans rapport (mesuré : le Wiktionnaire
        pour le mot « quel »). Lire cette page coûte du contexte et fausse la
        synthèse : on ne garde les résultats sans terme commun que s'il n'y a pas
        assez de sources pertinentes.
        """
        sources = dedupe_hits(list(hits))
        for source in sources:
            source.score = score_source(source, query)
        terms = key_terms(query)
        if terms:
            def _matches(source: Source) -> int:
                haystack = f"{source.title} {source.snippet} {source.domain}".lower()
                return sum(1 for term in terms if term in haystack)

            # Deux termes communs au moins : un seul suffit à faire entrer une
            # page d'homonymie (mesuré : « Niveau — Wikipédia » pour « niveau
            # actuel du prix du cacao »). Le filtre ne s'applique que s'il reste
            # assez de sources, pour ne jamais vider la recherche.
            strong = [source for source in sources if _matches(source) >= 2]
            if len(strong) >= 2:
                sources = strong
        sources.sort(key=lambda source: (-source.score, source.domain))
        return sources

    # -- lecture ----------------------------------------------------------
    async def _read_one(self, source: Source, *, semaphore: asyncio.Semaphore) -> ReadSource:
        async with semaphore:
            reading = ReadSource(
                url=source.url, title=source.title or source.domain, domain=source.domain, status="illisible"
            )
            try:
                validate_url_shape(
                    source.url,
                    self.settings.browser_domain_allowlist,
                    enforce_allowlist=not self.settings.browser_open_web,
                )
            except Exception as exc:  # noqa: BLE001 — domaine refusé : source écartée
                reading.status = "refusee"
                reading.note = str(exc)[:120]
                return reading

            fetcher = self._make_fetcher()
            try:
                page = await asyncio.wait_for(
                    fetcher(source.url),
                    timeout=self.settings.research_provider_timeout_seconds + 12,
                )
            except Exception as exc:  # noqa: BLE001 — page illisible : on le dira
                reading.note = f"lecture impossible ({type(exc).__name__})"
                return reading
            if getattr(page, "status", 200) >= 400:
                reading.note = f"HTTP {page.status}"
                return reading

            body = ""
            raw = getattr(page, "raw", None)
            if raw is not None and looks_like_pdf(raw, getattr(page, "content_type", "")):
                extraction = extract_pdf(
                    raw,
                    max_bytes=self.settings.research_pdf_max_bytes,
                    max_pages=self.settings.research_pdf_max_pages,
                )
                if extraction.status != "ok":
                    reading.note = extraction.error or "PDF illisible"
                    return reading
                body = extraction.text
                reading.title = reading.title or source.title
            else:
                readable = extract_readable(
                    getattr(page, "text", "") or "", getattr(page, "final_url", source.url)
                )
                body = readable.text
                if readable.title:
                    reading.title = readable.title[:200]
                if readable.injection_findings:
                    reading.note = "contenu potentiellement hostile neutralisé"

            body, _findings = sanitize_text(body)
            if len(body.strip()) < 80:
                reading.status = "vide"
                reading.note = reading.note or "texte extrait trop court"
                return reading

            passage = best_passage(body) or body[:600]
            reading.status = "lue"
            reading.chars = len(body)
            # Le passage le plus lisible en tête, puis le corps : le modèle voit
            # la phrase utile avant le chrome restant de la page.
            extrait = passage if passage and passage not in body[:400] else ""
            combined = (extrait + "\n" + body) if extrait else body
            reading.text = combined[: self.settings.deep_research_source_chars]
            reading.url = getattr(page, "final_url", None) or source.url
            return reading

    async def _read(self, sources: Sequence[Source]) -> list[ReadSource]:
        semaphore = asyncio.Semaphore(max(1, self.settings.research_concurrency))
        return list(
            await asyncio.gather(*(self._read_one(source, semaphore=semaphore) for source in sources))
        )

    # -- synthèse ---------------------------------------------------------
    def _build_messages(
        self, query: str, read: Sequence[ReadSource], unread: Sequence[ReadSource], language: str
    ) -> list[dict[str, Any]]:
        english = str(language).lower().startswith("en")
        system = SYSTEM_PROMPT_EN if english else SYSTEM_PROMPT_FR
        lines: list[str] = []
        for index, source in enumerate(read, start=1):
            lines.append(f"[{index}] {source.title} — {source.url} ({source.chars} caractères lus)")
            lines.append('"""')
            lines.append(source.text.strip())
            lines.append('"""')
            lines.append("")
        if unread:
            label = "Unread sources" if english else "Sources non lisibles"
            lines.append(f"{label} : " + "; ".join(f"{s.title} ({s.domain}) — {s.note or s.status}" for s in unread))
        header = "Question: " if english else "Question : "
        closing = "Write the synthesis now." if english else "Rédige maintenant la synthèse."
        user = "\n".join([f"{header}{query}", "", *lines, closing])
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _citation_indexes(self, text: str, total: int) -> list[int]:
        found: list[int] = []
        for match in _CITATION_RE.finditer(text):
            value = int(match.group(1))
            if 1 <= value <= total and value not in found:
                found.append(value)
        return sorted(found)

    def _appendix(self, read: Sequence[ReadSource], unread: Sequence[ReadSource], english: bool) -> str:
        lines: list[str] = ["", "Sources consulted:" if english else "Sources consultées :"]
        for index, source in enumerate(read, start=1):
            lines.append(f"[{index}] {source.title} — {source.url}")
        if unread:
            lines.append("")
            lines.append("Not used:" if english else "Sources non exploitées :")
            for source in unread:
                lines.append(f"- {source.title} ({source.domain}) : {source.note or source.status}")
        return "\n".join(lines)

    async def run(
        self,
        query: str,
        *,
        language: str = "fr",
        on_status: Callable[[str], None] | None = None,
    ) -> DeepResearchResult:
        started = time.monotonic()
        english = str(language).lower().startswith("en")
        queries = plan_deep_queries(
            query, language=language, count=self.settings.deep_research_max_queries
        )
        if on_status:
            on_status(f"Recherche approfondie : {len(queries)} requêtes…")

        hits, providers, warnings = await self._search(queries, "en" if english else "fr")
        if not hits:
            warnings.append(
                "Aucune source trouvée : les moteurs de recherche n'ont rien renvoyé. "
                "Aucune réponse n'est inventée."
            )
            return DeepResearchResult(
                answer=(
                    f"No exploitable source was found for “{query}”. The search ran but returned nothing."
                    if english
                    else f"Aucune source exploitable trouvée pour « {query} ». La recherche a bien été "
                    "exécutée, mais les moteurs n'ont rien renvoyé : aucune réponse n'est inventée."
                ),
                queries=queries,
                providers=providers,
                warnings=warnings,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        sources = self._select_sources(hits, query)
        selected = sources[: max(1, self.settings.deep_research_max_pages)]

        if on_status:
            on_status(f"Lecture de {len(selected)} page(s)…")
        readings = await self._read(selected)
        read = [r for r in readings if r.status == "lue" and r.text.strip()]
        unread = [r for r in readings if r.status != "lue"]
        for source in unread:
            warnings.append(f"{source.domain} non exploitée : {source.note or source.status}")

        if not read:
            warnings.append(
                "Aucune page n'a pu être lue : la réponse n'est pas rédigée, "
                "car un titre de résultat n'est pas une preuve."
            )
            listed = ", ".join(f"{s.domain} ({s.note or s.status})" for s in unread[:5])
            return DeepResearchResult(
                answer=(
                    f"The {len(selected)} selected pages could not be read ({listed}). "
                    "No synthesis is produced rather than inventing one."
                    if english
                    else f"Les {len(selected)} pages retenues n'ont pas pu être lues ({listed}). "
                    "Aucune synthèse n'est produite plutôt que d'en inventer une."
                ),
                sources=readings,
                queries=queries,
                providers=providers,
                warnings=warnings,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        llm = self.llm
        if llm is None:
            listed = "\n".join(f"[{i}] {s.title} — {s.url}" for i, s in enumerate(read, start=1))
            return DeepResearchResult(
                answer=(
                    "Synthèse indisponible : aucune clé DeepSeek n'est configurée. "
                    "Pages réellement lues :\n" + listed
                ),
                sources=readings,
                queries=queries,
                providers=providers,
                warnings=warnings + ["Synthèse non rédigée : clé DeepSeek absente."],
                error="PROVIDER_NOT_CONFIGURED",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        if on_status:
            on_status("Synthèse citée…")
        messages = self._build_messages(query, read, unread, language)
        body = ""
        model = ""
        consommation: dict[str, Any] = {}
        error: str | None = None
        try:
            result: LLMResult = await llm.chat(
                messages,
                purpose="research",
                max_tokens=self.settings.deepseek_max_output_tokens,
                timeout=self.settings.deepseek_timeout_seconds,
            )
            body = (result.content or "").strip()
            model = result.model
            consommation = dict(result.usage or {})
        except LLMError as exc:
            error = exc.code
            logger.warning("Recherche approfondie : synthèse en échec (%s)", exc.code)
            listed = "\n".join(f"[{i}] {s.title} — {s.url}" for i, s in enumerate(read, start=1))
            body = (
                f"La synthèse n'a pas pu être rédigée : {exc.message} "
                "Les pages ci-dessous ont bien été lues ; aucune conclusion n'est inventée.\n\n"
                f"{listed}"
            )

        citations = self._citation_indexes(body, len(read))
        answer = body + self._appendix(read, unread, english)
        return DeepResearchResult(
            answer=answer.strip(),
            sources=readings,
            queries=queries,
            providers=providers,
            warnings=warnings,
            citations=citations,
            model=model,
            usage=consommation,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=error,
        )

"""Skill web_research — recherche et synthèse de sources web accessibles.

Toute page lue est traitée comme une donnée NON FIABLE : les instructions
qu'elle contient ne sont jamais suivies, les lignes suspectes sont neutralisées
et signalées dans `limits`.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

from app.skills.base import (
    FetchedPage,
    SkillContext,
    SkillProviderError,
    SkillResult,
    SkillValidationError,
)
from app.skills.fetch import (
    ensure_text,
    extract_readable,
    parse_json_page,
    validate_url_shape,
)

SEARCH_ENDPOINT = "https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1&t=kwes"
WIKI_ENDPOINT = (
    "https://fr.wikipedia.org/w/api.php?action=query&list=search&srsearch={query}"
    "&srlimit={limit}&format=json&utf8=1"
)
DEPTH_LIMIT = {"quick": 1, "standard": 3, "deep": 5}
SNIPPET_CHARS = 240
_TAG_RE = re.compile(r"<[^>]+>")


def _collect_topics(node: Any, out: list[dict[str, str]], limit: int) -> None:
    if len(out) >= limit:
        return
    if isinstance(node, dict):
        url = node.get("FirstURL")
        text = node.get("Text")
        if isinstance(url, str) and isinstance(text, str) and url.startswith("http"):
            out.append({"url": url, "title": text.split(" - ")[0][:160], "text": text})
        topics = node.get("Topics")
        if isinstance(topics, list):
            for item in topics:
                _collect_topics(item, out, limit)
    elif isinstance(node, list):
        for item in node:
            _collect_topics(item, out, limit)


def _is_navigation(block: str) -> bool:
    lowered = block.lower()
    nav_hints = (
        "aller au contenu",
        "menu principal",
        "déplacer vers la barre latérale",
        "navigation",
        "rechercher",
        "créer un compte",
        "se connecter",
        "outils personnels",
        "page d'accueil",
        "imprimer / exporter",
        "autres projets",
        "afficher",
        "masquer",
        "sous-section",
        "modifier le code",
        "cookie",
    )
    return any(hint in lowered for hint in nav_hints)


def _best_block(text: str) -> str:
    """Premier bloc de contenu substantiel, hors chrome de navigation."""
    blocks = [block.strip() for block in text.splitlines() if block.strip()]
    for block in blocks:
        if len(block) >= 90 and not _is_navigation(block):
            return block
    for block in blocks:
        if len(block) >= 60:
            return block
    return re.sub(r"\s+", " ", text).strip()


def _snippet(text: str) -> str:
    block = _best_block(text)
    if not block:
        return ""
    cut = block[:SNIPPET_CHARS]
    if len(block) > SNIPPET_CHARS:
        last_space = cut.rfind(" ")
        if last_space > 80:
            cut = cut[:last_space]
        cut += "…"
    return cut


def _first_fact(text: str) -> str:
    block = _best_block(text)
    if not block:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", block)[0]
    return sentence[:220]


async def _duckduckgo(
    query: str, ctx: SkillContext, limit: int
) -> tuple[list[dict[str, str]], list[str]]:
    limits: list[str] = []
    endpoint = SEARCH_ENDPOINT.format(query=quote_plus(query))
    try:
        page = await ctx.fetch(endpoint)
    except SkillValidationError:
        raise
    except Exception as exc:
        raise SkillProviderError("Moteur de recherche injoignable.") from exc

    payload = parse_json_page(page)
    if not payload:
        limits.append("Le moteur DuckDuckGo n'a pas renvoyé de JSON exploitable.")
        return [], limits

    results: list[dict[str, str]] = []
    _collect_topics(payload.get("RelatedTopics") or [], results, limit)
    abstract = payload.get("AbstractText")
    abstract_url = payload.get("AbstractURL")
    if isinstance(abstract, str) and isinstance(abstract_url, str) and abstract_url.startswith("http"):
        results.insert(0, {"url": abstract_url, "title": str(payload.get("Heading") or query)[:160], "text": abstract})
    return results[:limit], limits


async def _wikipedia(
    query: str, ctx: SkillContext, limit: int
) -> tuple[list[dict[str, str]], list[str]]:
    """Repli keyless sur l'API de recherche Wikipédia (domaine allowlisté)."""
    endpoint = WIKI_ENDPOINT.format(query=quote_plus(query), limit=max(1, limit))
    try:
        page = await ctx.fetch(endpoint)
    except SkillValidationError:
        raise
    except Exception as exc:
        raise SkillProviderError("API Wikipedia injoignable.") from exc

    payload = parse_json_page(page)
    items = ((payload.get("query") or {}).get("search")) or []
    results: list[dict[str, str]] = []
    for item in items[:limit]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        snippet = _TAG_RE.sub("", str(item.get("snippet") or "")).strip()
        results.append(
            {
                "url": "https://fr.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                "title": title[:160],
                "text": snippet,
            }
        )
    return results, ([] if results else ["Aucun résultat Wikipédia pour cette requête."])


async def _search(
    query: str, ctx: SkillContext, limit: int
) -> tuple[list[dict[str, str]], list[str]]:
    limits: list[str] = []
    unreachable = 0
    results: list[dict[str, str]] = []

    try:
        results, ddg_limits = await _duckduckgo(query, ctx, limit)
        limits.extend(ddg_limits)
    except SkillProviderError:
        unreachable += 1
        limits.append("Moteur DuckDuckGo injoignable, repli Wikipédia tenté.")

    if not results:
        try:
            wiki_results, wiki_limits = await _wikipedia(query, ctx, limit)
            if wiki_results:
                results = wiki_results
                limits.append("Sources issues de l'API Wikipédia (moteur principal vide).")
            limits.extend(wiki_limits)
        except SkillProviderError:
            unreachable += 1
            limits.append("API Wikipédia injoignable.")

    if not results and unreachable >= 2:
        raise SkillProviderError("Aucun moteur de recherche joignable dans le périmètre autorisé.")
    return results[:limit], limits


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    query = str(payload["query"]).strip()
    depth = payload.get("depth") or "standard"
    scope = payload.get("scope")
    limit = DEPTH_LIMIT.get(str(depth), 3)

    ctx.logger.info("web_research query=%r depth=%s", query[:80], depth)
    candidates, limits = await _search(query, ctx, limit + 2)

    sources: list[dict[str, str]] = []
    facts: list[str] = []
    skipped: list[str] = []

    for candidate in candidates:
        if len(sources) >= limit:
            break
        url = candidate["url"]
        try:
            validate_url_shape(url, ctx.allowlist)
        except SkillValidationError:
            host = urlsplit(url).hostname or url[:60]
            if host not in skipped:
                skipped.append(host)
            continue
        try:
            page: FetchedPage = await ctx.fetch(url)
        except Exception as exc:
            ctx.logger.warning("Lecture impossible url=%s err=%s", url[:120], type(exc).__name__)
            continue
        if page.status >= 400:
            continue

        extracted = extract_readable(page.text, page.final_url or url)
        # Le texte de recherche (fournisseur) est plus propre que le chrome de la
        # page ; la page reste lue (preuve d'accès) et sert de repli.
        snippet = _snippet(candidate.get("text", "")) or _snippet(extracted.text)
        if not snippet:
            continue
        sources.append(
            {
                "url": page.final_url or url,
                "title": extracted.title or candidate["title"],
                "snippet": snippet,
                "domain": urlsplit(page.final_url or url).hostname or "",
            }
        )
        fact = _first_fact(candidate.get("text", "")) or _first_fact(extracted.text)
        if fact and fact not in facts:
            facts.append(fact)
        if extracted.injection_findings:
            limits.append(
                "Contenu potentiellement hostile neutralisé dans une source "
                f"({', '.join(extracted.injection_findings)})."
            )

    if skipped:
        limits.append(
            f"{len(skipped)} domaine(s) hors allowlist non consultés : {', '.join(skipped[:5])}."
        )
    if not sources:
        limits.append("Aucune source exploitable n'a pu être lue dans le périmètre autorisé.")

    scope_note = f" Périmètre demandé : {scope}." if scope else ""
    if sources:
        synthesis = (
            f"{len(sources)} source(s) lue(s) pour « {query} »{scope_note} "
            "Les éléments ci-dessous sont des citations de pages tierces, non vérifiées : "
            + " ".join(f"[{i + 1}] {s['title']} — {s['snippet'][:160]}" for i, s in enumerate(sources))
        )
    else:
        synthesis = (
            f"Aucune donnée vérifiable collectée pour « {query} »{scope_note}. "
            "La synthèse est volontairement vide plutôt qu'inventée."
        )

    limits.append("Contenu web non fiable : aucune instruction issue d'une page n'a été exécutée.")
    if ctx.settings.llm_is_mock:
        limits.append("Le fournisseur LLM est en mode MOCK (DEEPSEEK_API_KEY absente).")

    ensure_text(synthesis, minimum=20)
    output = {
        "sources": sources,
        "facts": facts,
        "synthesis": synthesis,
        "limits": limits,
        "skipped_sources": skipped,
    }
    return SkillResult(
        output=output,
        summary=f"{len(sources)} source(s) lue(s), {len(facts)} fait(s) cité(s).",
        evidence=[{"type": "source", "url": s["url"]} for s in sources],
    )

"""Fournisseurs de recherche, cache et quotas.

Ordre de routage : SearXNG (auto-hébergé, 0 FCFA) → DuckDuckGo → Wikipédia.
Si aucun fournisseur ne répond, le résultat est un échec explicite : aucune
source n'est inventée et aucune recherche n'est annoncée comme effectuée.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict
from typing import Any, Protocol
from urllib.parse import quote_plus

import httpx

from app.research.core import SearchHit

logger = logging.getLogger("kwes.research")

_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return _TAGS.sub(" ", text or "").replace("&quot;", '"').replace("&amp;", "&").strip()


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, limit: int, language: str) -> list[SearchHit]: ...

    async def healthy(self) -> bool: ...


class _BaseProvider:
    name = "base"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def healthy(self) -> bool:  # pragma: no cover - surchargé
        return True


class SearxngProvider(_BaseProvider):
    """SearXNG auto-hébergé : JSON natif, aucune clé, aucun abonnement."""

    name = "searxng"

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        super().__init__(client)
        self.base_url = base_url.rstrip("/")

    async def search(self, query: str, limit: int, language: str) -> list[SearchHit]:
        response = await self._client.get(
            f"{self.base_url}/search",
            params={
                "q": query,
                "format": "json",
                "language": language,
                "safesearch": 0,
                "pageno": 1,
            },
            timeout=12.0,
        )
        response.raise_for_status()
        payload = response.json()
        hits: list[SearchHit] = []
        for rank, item in enumerate(payload.get("results") or []):
            url = str(item.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            hits.append(
                SearchHit(
                    url=url,
                    title=_clean(str(item.get("title") or ""))[:300],
                    snippet=_clean(str(item.get("content") or ""))[:400],
                    provider=self.name,
                    rank=rank,
                    published_at=item.get("publishedDate"),
                    extra={"engines": ",".join(item.get("engines") or [])[:200]},
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def healthy(self) -> bool:
        try:
            response = await self._client.get(f"{self.base_url}/healthz", timeout=3.0)
            return response.status_code == 200
        except Exception:  # noqa: BLE001 — un fournisseur en panne n'est pas une erreur fatale
            return False


class DuckDuckGoProvider(_BaseProvider):
    """API Instant Answer : gratuite, sans clé, couverture limitée mais stable."""

    name = "duckduckgo"
    ENDPOINT = "https://api.duckduckgo.com/"

    def _collect(self, node: Any, out: list[SearchHit], limit: int) -> None:
        if len(out) >= limit:
            return
        if isinstance(node, dict):
            url = node.get("FirstURL")
            text = node.get("Text")
            if isinstance(url, str) and isinstance(text, str) and url.startswith("http"):
                out.append(
                    SearchHit(
                        url=url,
                        title=_clean(text.split(" - ")[0])[:300],
                        snippet=_clean(text)[:400],
                        provider=self.name,
                        rank=len(out),
                    )
                )
            for child in node.get("Topics") or []:
                self._collect(child, out, limit)
        elif isinstance(node, list):
            for child in node:
                self._collect(child, out, limit)

    async def search(self, query: str, limit: int, language: str) -> list[SearchHit]:
        response = await self._client.get(
            self.ENDPOINT,
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1, "t": "kwes"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        hits: list[SearchHit] = []
        abstract_url = payload.get("AbstractURL")
        if isinstance(abstract_url, str) and abstract_url.startswith("http"):
            hits.append(
                SearchHit(
                    url=abstract_url,
                    title=_clean(str(payload.get("Heading") or query))[:300],
                    snippet=_clean(str(payload.get("AbstractText") or ""))[:400],
                    provider=self.name,
                    rank=0,
                )
            )
        self._collect(payload.get("RelatedTopics") or [], hits, limit)
        return hits[:limit]


class WikipediaProvider(_BaseProvider):
    """Wikipédia : encyclopédique, utile pour définir et contextualiser."""

    name = "wikipedia"
    ENDPOINT = "https://{lang}.wikipedia.org/w/api.php"

    async def search(self, query: str, limit: int, language: str) -> list[SearchHit]:
        lang = "fr" if language.startswith("fr") else "en"
        response = await self._client.get(
            self.ENDPOINT.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "utf8": 1,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        items = ((response.json().get("query") or {}).get("search") or [])[:limit]
        hits: list[SearchHit] = []
        for rank, item in enumerate(items):
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            hits.append(
                SearchHit(
                    url=f"https://{lang}.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
                    title=title[:300],
                    snippet=_clean(str(item.get("snippet") or ""))[:400],
                    provider=self.name,
                    rank=rank,
                )
            )
        return hits


# ---------------------------------------------------------------------------
# Cache et quotas
# ---------------------------------------------------------------------------
class ResearchCache:
    """Cache Redis (TTL 24 h par défaut) avec repli mémoire pour les tests."""

    def __init__(self, client: Any | None, ttl_seconds: int = 86_400, enabled: bool = True) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._enabled = enabled
        self._memory: dict[str, tuple[float, str]] = {}

    @staticmethod
    def key(provider: str, query: str, limit: int, language: str) -> str:
        digest = hashlib.sha256(f"{provider}|{query}|{limit}|{language}".encode()).hexdigest()[:32]
        return f"kwes:research:cache:{digest}"

    async def get(self, key: str) -> list[SearchHit] | None:
        if not self._enabled:
            return None
        if self._client is None:
            entry = self._memory.get(key)
            if entry is None:
                return None
            expires_at, payload = entry
            if expires_at < time.time():
                self._memory.pop(key, None)
                return None
            return [SearchHit(**item) for item in json.loads(payload)]
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001 — un cache indisponible ne bloque pas la recherche
            logger.warning("Cache lecture impossible (%s)", type(exc).__name__)
            return None
        if not raw:
            return None
        try:
            return [SearchHit(**item) for item in json.loads(raw)]
        except (ValueError, TypeError):
            return None

    async def set(self, key: str, hits: list[SearchHit]) -> None:
        if not self._enabled:
            return
        payload = json.dumps([asdict(hit) for hit in hits], ensure_ascii=False)
        if self._client is None:
            self._memory[key] = (time.time() + self._ttl, payload)
            return
        try:
            await self._client.set(key, payload, ex=self._ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache écriture impossible (%s)", type(exc).__name__)

    async def quota_used(self, provider: str) -> int:
        key = f"kwes:research:quota:{provider}:{time.strftime('%Y%m%d')}"
        if self._client is None:
            return 0
        try:
            value = await self._client.get(key)
            return int(value or 0)
        except Exception:  # noqa: BLE001
            return 0

    async def quota_consume(self, provider: str, limit: int) -> bool:
        """Consomme une unité de quota. Renvoie False si la limite est atteinte."""
        key = f"kwes:research:quota:{provider}:{time.strftime('%Y%m%d')}"
        if self._client is None:
            return True
        try:
            value = await self._client.incr(key)
            if value == 1:
                await self._client.expire(key, 86_400)
            return int(value) <= limit
        except Exception:  # noqa: BLE001 — quota indisponible : on ne bloque pas la recherche
            return True


# ---------------------------------------------------------------------------
# Routeur
# ---------------------------------------------------------------------------
class ProviderRouter:
    """Essaie les fournisseurs dans l'ordre, s'arrête dès qu'il y a assez de résultats."""

    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        cache: ResearchCache,
        daily_limit: int,
        min_results: int = 3,
    ) -> None:
        self.providers = providers
        self.cache = cache
        self.daily_limit = daily_limit
        self.min_results = min_results
        self.failures: dict[str, str] = {}

    async def search(self, query: str, limit: int, language: str = "fr") -> tuple[list[SearchHit], list[str], list[str]]:
        """Renvoie (résultats, fournisseurs utilisés, avertissements)."""
        collected: list[SearchHit] = []
        used: list[str] = []
        warnings: list[str] = []
        for provider in self.providers:
            if len(collected) >= self.min_results:
                break
            if provider.name in self.failures:
                warnings.append(f"{provider.name} ignoré : {self.failures[provider.name]}")
                continue
            key = self.cache.key(provider.name, query, limit, language)
            cached = await self.cache.get(key)
            if cached is not None:
                collected.extend(cached)
                used.append(f"{provider.name} (cache)")
                continue
            if not await self.cache.quota_consume(provider.name, self.daily_limit):
                self.failures[provider.name] = "quota quotidien atteint"
                warnings.append(f"{provider.name} : quota quotidien atteint.")
                continue
            try:
                hits = await provider.search(query, limit, language)
            except Exception as exc:  # noqa: BLE001 — un fournisseur en panne ne casse pas la recherche
                self.failures[provider.name] = f"indisponible ({type(exc).__name__})"
                warnings.append(f"{provider.name} indisponible ({type(exc).__name__}).")
                logger.warning("Fournisseur %s en échec: %s", provider.name, type(exc).__name__)
                continue
            await self.cache.set(key, hits)
            if hits:
                collected.extend(hits)
                used.append(provider.name)
            else:
                warnings.append(f"{provider.name} n'a renvoyé aucun résultat.")
        return collected[: limit * 2], used, warnings


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "Kwes/1.0 (+https://kwes.local; recherche documentaire)"},
        timeout=httpx.Timeout(15.0, connect=5.0),
    )


async def build_router(
    *, searxng_url: str, cache: ResearchCache, daily_limit: int
) -> tuple[ProviderRouter, httpx.AsyncClient]:
    client = build_client()
    providers: list[SearchProvider] = [
        SearxngProvider(client, searxng_url),
        DuckDuckGoProvider(client),
        WikipediaProvider(client),
    ]
    return ProviderRouter(providers, cache=cache, daily_limit=daily_limit), client


async def gather_with_limit(coros: list[Any], limit: int) -> list[Any]:
    """Exécute des coroutines avec une concurrence bornée (protection anti-boucle)."""
    semaphore = asyncio.Semaphore(max(1, limit))

    async def run(coro: Any) -> Any:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)

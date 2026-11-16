"""Fournisseurs, routage, cache et quotas — sans aucun appel réseau réel."""

from __future__ import annotations

import json

import httpx
import pytest

from app.research.providers import (
    DuckDuckGoProvider,
    ProviderRouter,
    ResearchCache,
    SearxngProvider,
    WikipediaProvider,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _searx_payload(n: int = 3) -> dict:
    return {
        "results": [
            {
                "url": f"https://example{i}.com/page?utm_source=x",
                "title": f"Résultat {i}",
                "content": f"Contenu {i}",
                "engines": ["google"],
            }
            for i in range(n)
        ]
    }


async def test_searxng_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json=_searx_payload())

    provider = SearxngProvider(_client(handler), "http://127.0.0.1:8888")
    hits = await provider.search("kwes", 3, "fr")
    assert len(hits) == 3
    assert hits[0].provider == "searxng"
    assert hits[0].title == "Résultat 0"


async def test_searxng_unhealthy_returns_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    provider = SearxngProvider(_client(handler), "http://127.0.0.1:8888")
    assert await provider.healthy() is False


async def test_duckduckgo_flattens_topics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Heading": "Kwes",
                "AbstractText": "Assistant vocal.",
                "AbstractURL": "https://example.com/kwes",
                "RelatedTopics": [
                    {"Text": "Sujet un", "FirstURL": "https://example.com/1"},
                    {"Topics": [{"Text": "Sujet deux", "FirstURL": "https://example.com/2"}]},
                ],
            },
        )

    provider = DuckDuckGoProvider(_client(handler))
    hits = await provider.search("kwes", 5, "fr")
    assert [h.url for h in hits] == [
        "https://example.com/kwes",
        "https://example.com/1",
        "https://example.com/2",
    ]


async def test_wikipedia_builds_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"query": {"search": [
                {"title": "Assistant personnel", "snippet": "<span>Un</span> assistant"},
                {"title": "Intelligence artificielle", "snippet": "IA"},
            ]}},
        )

    provider = WikipediaProvider(_client(handler))
    hits = await provider.search("assistant", 2, "fr")
    assert hits[0].url.startswith("https://fr.wikipedia.org/wiki/")
    assert "<span>" not in hits[0].snippet


async def test_router_falls_back_when_first_provider_fails() -> None:
    calls: list[str] = []

    class Failing:
        name = "searxng"

        async def search(self, query, limit, language):
            calls.append("searxng")
            raise httpx.ConnectError("down")

    class Working:
        name = "duckduckgo"

        async def search(self, query, limit, language):
            calls.append("duckduckgo")
            from app.research.core import SearchHit

            return [SearchHit("https://a.fr", "A", "s", "duckduckgo")]

    router = ProviderRouter(
        [Failing(), Working()], cache=ResearchCache(None), daily_limit=100, min_results=1
    )
    hits, used, warnings = await router.search("q", 5)
    assert calls == ["searxng", "duckduckgo"]
    assert used == ["duckduckgo"]
    assert any("searxng" in w for w in warnings)
    assert len(hits) == 1


async def test_router_uses_cache_second_time() -> None:
    calls = 0

    class Provider:
        name = "searxng"

        async def search(self, query, limit, language):
            nonlocal calls
            calls += 1
            from app.research.core import SearchHit

            return [SearchHit("https://a.fr", "A", "s", "searxng")]

    cache = ResearchCache(None, ttl_seconds=60)
    router = ProviderRouter([Provider()], cache=cache, daily_limit=100, min_results=1)
    await router.search("q", 5)
    await router.search("q", 5)
    assert calls == 1


async def test_router_stops_when_quota_is_exhausted() -> None:
    class Provider:
        name = "searxng"

        async def search(self, query, limit, language):
            raise AssertionError("ne doit pas être appelé")

    class Quota(ResearchCache):
        async def quota_consume(self, provider: str, limit: int) -> bool:
            return False

    router = ProviderRouter([Provider()], cache=Quota(None), daily_limit=1, min_results=1)
    hits, used, warnings = await router.search("q", 5)
    assert hits == [] and used == []
    assert any("quota" in w.lower() for w in warnings)


async def test_router_reports_empty_result_without_inventing() -> None:
    class Empty:
        name = "searxng"

        async def search(self, query, limit, language):
            return []

    router = ProviderRouter([Empty()], cache=ResearchCache(None), daily_limit=10, min_results=1)
    hits, used, warnings = await router.search("q", 5)
    assert hits == []
    assert any("aucun résultat" in w.lower() for w in warnings)


async def test_cache_survives_redis_outage() -> None:
    class Broken:
        async def get(self, key):
            raise ConnectionError("redis down")

        async def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

        async def incr(self, key):
            raise ConnectionError("redis down")

        async def expire(self, key, ttl):
            raise ConnectionError("redis down")

    cache = ResearchCache(Broken(), ttl_seconds=60)
    assert await cache.get("k") is None
    await cache.set("k", [])  # ne lève pas
    assert await cache.quota_consume("searxng", 1) is True


def test_cache_key_depends_on_all_parameters() -> None:
    a = ResearchCache.key("searxng", "q", 5, "fr")
    b = ResearchCache.key("searxng", "q", 5, "en")
    c = ResearchCache.key("searxng", "q", 5, "fr")
    assert a != b and a == c


def test_cache_payload_roundtrip() -> None:
    cache = ResearchCache(None, ttl_seconds=60)
    from app.research.core import SearchHit

    hits = [SearchHit("https://a.fr", "A", "s", "searxng", 1)]
    import asyncio

    async def scenario():
        await cache.set("k", hits)
        return await cache.get("k")

    restored = asyncio.run(scenario())
    assert restored and restored[0].url == "https://a.fr"
    assert restored[0].provider == "searxng"

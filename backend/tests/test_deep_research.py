"""Recherche approfondie : requêtes réelles multiples, lectures réelles, citations.

Aucun réseau : la recherche et le fetcher sont remplacés par des doubles
déterministes, le modèle par un scénario. Ce qui est vérifié ici est le parcours
(plusieurs requêtes → plusieurs pages → synthèse citée) et l'honnêteté des cas
dégradés (page illisible, clé refusée, aucune page lue).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.deep_research import DeepResearchRunner, plan_deep_queries
from app.agent.llm import LLMError, LLMResult
from app.agent.llm import _classify
from app.research.core import SearchHit
from app.skills.base import FetchedPage
from app.skills.registry import SkillRegistry  # noqa: F401  (type des fixtures)

PAGES = {
    "https://fr.wikipedia.org/wiki/Cacao": (
        "<html><head><title>Cacao — Wikipédia</title></head><body><main>"
        "<p>Le cacao est la poudre obtenue à partir des fèves de cacaoyer, "
        "cultivées principalement en Afrique de l'Ouest. La Côte d'Ivoire et le "
        "Ghana figurent parmi les premiers producteurs mondiaux de fèves.</p>"
        "<p>Les prix internationaux sont fixés à Londres et à New York, puis "
        "répercutés sur les producteurs avec un décalage de plusieurs mois.</p>"
        "</main></body></html>"
    ),
    "https://fr.wikipedia.org/wiki/Côte_d'Ivoire": (
        "<html><head><title>Côte d'Ivoire — Wikipédia</title></head><body><main>"
        "<p>La Côte d'Ivoire est le premier producteur mondial de cacao, avec "
        "environ quarante pour cent de l'offre mondiale selon les campagnes.</p>"
        "</main></body></html>"
    ),
    "https://en.wikipedia.org/wiki/Cocoa_bean": (
        "<html><head><title>Cocoa bean — Wikipedia</title></head><body><main>"
        "<p>Cocoa beans are the dried and fully fermented seeds of Theobroma "
        "cacao, used to make chocolate, cocoa butter and cocoa solids.</p>"
        "</main></body></html>"
    ),
}

HITS = [
    SearchHit(url=url, title=url.rsplit("/", 1)[-1].replace("_", " "), snippet="extrait sur le cacao en Côte d'Ivoire", provider="searxng", rank=i)
    for i, url in enumerate(PAGES)
] + [
    SearchHit(
        url="https://example.com/page-inaccessible",
        title="Page inaccessible",
        snippet="extrait sur le cacao en Côte d'Ivoire",
        provider="searxng",
        rank=9,
    )
]


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def __call__(self, query: str) -> list[SearchHit]:
        self.queries.append(query)
        return list(HITS)


class FakeFetcher:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.urls: list[str] = []

    async def __call__(self, url: str) -> FetchedPage:
        self.urls.append(url)
        if url in self.fail:
            raise RuntimeError("connexion refusée")
        return FetchedPage(
            url=url,
            final_url=url,
            status=200,
            content_type="text/html",
            text=PAGES[url],
        )


class ScriptedLLM:
    def __init__(self, content: str = "Synthèse [1] et [2].", error: LLMError | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[list[dict]] = []

    async def chat(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append([dict(m) for m in messages])
        if self.error is not None:
            raise self.error
        return LLMResult(
            content=self.content,
            usage={"input_tokens": 800, "output_tokens": 120, "total_tokens": 920},
            model="deepseek-chat",
        )


def _runner(settings, *, llm=None, fail: set[str] | None = None):
    search = FakeSearch()
    fetcher = FakeFetcher(fail=fail)
    runner = DeepResearchRunner(settings, llm=llm, fetcher=fetcher, search=search)
    return runner, search, fetcher


@pytest.mark.asyncio
async def test_deep_research_runs_several_queries_reads_pages_and_cites(settings) -> None:
    llm = ScriptedLLM("La Côte d'Ivoire domine l'offre [1]. Les prix sont fixés à Londres [2].")
    runner, search, fetcher = _runner(settings, llm=llm, fail={"https://example.com/page-inaccessible"})

    result = await runner.run("Marché du cacao en Côte d'Ivoire", language="fr")

    # 3 à 5 requêtes réellement exécutées, toutes dérivées de la demande.
    assert 3 <= len(search.queries) <= 5
    assert all("cacao" in q.lower() for q in search.queries)
    assert result.queries == search.queries

    # 3 à 5 pages tentées, les lisibles réellement lues.
    assert 3 <= len(fetcher.urls) <= 5
    assert result.read_count >= 3
    assert result.cited_count == 2
    assert result.citations == [1, 2]
    assert result.error is None

    # Le modèle a reçu le texte réel des pages, pas seulement les titres.
    prompt = llm.calls[0][-1]["content"]
    assert "premier producteur mondial de cacao" in prompt
    assert "[1]" in prompt

    # La réponse cite et liste des URLs réellement lues.
    assert "[1]" in result.answer
    assert "Sources consultées" in result.answer
    for source in result.sources:
        if source.status == "lue":
            assert source.url in result.answer
    # La page en échec est nommée, jamais passée sous silence.
    assert "example.com" in result.answer
    assert any("non exploitée" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_deep_research_invents_nothing_when_no_page_can_be_read(settings) -> None:
    llm = ScriptedLLM()
    runner, _, _ = _runner(settings, llm=llm, fail=set(PAGES) | {"https://example.com/page-inaccessible"})

    result = await runner.run("Marché du cacao", language="fr")

    assert llm.calls == []  # aucun appel modèle : rien à synthétiser
    assert result.read_count == 0
    assert result.cited_count == 0
    assert "n'ont pas pu être lues" in result.answer
    assert "Aucune synthèse n'est produite" in result.answer


@pytest.mark.asyncio
async def test_deep_research_reports_refused_key_without_faking_synthesis(settings) -> None:
    llm = ScriptedLLM(error=LLMError("Clé DeepSeek refusée (401).", retryable=False, code="PROVIDER_AUTH"))
    runner, _, _ = _runner(settings, llm=llm, fail={"https://example.com/page-inaccessible"})

    result = await runner.run("Marché du cacao", language="fr")

    assert result.error == "PROVIDER_AUTH"
    assert "n'a pas pu être rédigée" in result.answer
    assert "Clé DeepSeek refusée" in result.answer
    assert result.read_count >= 3  # les pages lues restent citées
    assert "Sources consultées" in result.answer


def test_plan_deep_queries_drops_the_instruction_and_keeps_the_subject() -> None:
    queries = plan_deep_queries(
        "Fais une recherche approfondie sur la production de coton au Bénin en 2026.",
        language="fr",
        count=4,
    )
    assert 3 <= len(queries) <= 5
    assert queries[0] == "production de coton au Bénin en 2026"
    assert all("recherche approfondie" not in query.lower() for query in queries)


def test_deep_research_intent_is_routed_before_mission() -> None:
    assert _classify("Fais une recherche approfondie sur le marché du cacao") == "recherche"
    assert _classify("Compare plusieurs sources sur le prix du cacao") == "recherche"
    assert _classify("Fais une recherche multi-sources sur la filière cacao") == "recherche"
    # Les demandes ordinaires gardent leur route.
    assert _classify("Quel est le prix du cacao aujourd'hui ?") == "outil"
    assert _classify("Prépare un rapport complet sur le cacao") == "mission"


def test_chat_mode_recherche_returns_cited_answer(
    client: TestClient, app, settings, headers: dict[str, str]
) -> None:
    llm = ScriptedLLM("La Côte d'Ivoire est le premier producteur [1].")
    runner, search, _ = _runner(settings, llm=llm, fail={"https://example.com/page-inaccessible"})
    app.state.orchestrator.deep_research = runner

    response = client.post(
        "/api/v1/chat",
        json={"message": "Fais une recherche approfondie sur le marché du cacao", "mode": "recherche"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "direct"
    assert "[1]" in body["response"]
    assert "Sources consultées" in body["response"]
    assert len(search.queries) >= 3

    messages = client.get(
        f"/api/v1/conversations/{body['conversation_id']}/messages", headers=headers
    ).json()
    assistant = messages[-1]
    assert assistant["role"] == "assistant"
    research = assistant["metadata"]["research"]
    assert research["sources_read"] >= 3
    assert research["model"] == "deepseek-chat"
    assert assistant["metadata"]["tools"][0]["name"] == "deep_research"
    # Les URLs exposées sont celles réellement lues, pas des placeholders.
    assert all(source["status"] in {"lue", "illisible", "vide", "refusee"} for source in research["sources"])
    json.dumps(research)  # sérialisable dans le champ JSON du message

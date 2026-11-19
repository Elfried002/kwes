"""Runtime d'agent : outils autorisés seulement, budget, preuves, journal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.agents.contracts import AgentTask
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime, MissionScope
from app.skills.base import SkillResult

PACKAGE = Path(__file__).resolve().parents[2] / "docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1"


@dataclass
class FauxLLM:
    """Réponses programmées : liste de tours (tool_calls ou texte)."""

    tours: list[dict[str, Any]]
    appels: int = 0

    async def chat(self, messages, *, tools=None, **kwargs):  # noqa: ANN001
        from app.agent.llm import LLMResult

        tour = self.tours[min(self.appels, len(self.tours) - 1)]
        self.appels += 1
        return LLMResult(
            content=tour.get("content", ""),
            tool_calls=tour.get("tool_calls", []),
            model="faux",
        )


@dataclass
class FauxSkill:
    manifest: Any
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


class FauxRegistry:
    """Registre minimal : un outil renvoie une source, l'autre échoue."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict[str, Any]]] = []

    def get(self, name: str):  # noqa: ANN201
        if name not in {"web_research", "code_exec"}:
            return None
        manifest = type("M", (), {"description": name, "permissions": []})()
        return FauxSkill(manifest=manifest)

    async def execute(self, name: str, payload: dict[str, Any], ctx):  # noqa: ANN001, ANN201
        self.executes.append((name, payload))
        if name == "web_research":
            return SkillResult(
                output={"results": [{"url": "https://example.org/source", "title": "Source"}]},
                summary="2 sources trouvées",
            )
        return SkillResult(output={"stdout": "42"}, summary="exécuté")


@pytest.fixture()
def registry_agents() -> AgentRegistry:
    if not PACKAGE.exists():
        pytest.skip("package agentique absent")
    return AgentRegistry(PACKAGE).load()


def _task(**overrides) -> AgentTask:  # noqa: ANN003
    base = dict(
        mission_id=uuid.uuid4(),
        agent_id="kwes.research",
        objective="Trouver le prix du cacao en Côte d'Ivoire",
        expected_output="Prix daté et sourcé",
        allowed_tools=["web.search"],
    )
    base.update(overrides)
    return AgentTask(**base)


def _scope() -> MissionScope:
    return MissionScope(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), mission_id=uuid.uuid4())


def _runtime(agents: AgentRegistry, llm: FauxLLM, skills: FauxRegistry) -> AgentRuntime:
    settings = type("S", (), {"browser_allowlist": []})()
    return AgentRuntime(settings=settings, agents=agents, skills=skills, llm=llm, fetcher=None)


@pytest.mark.asyncio()
async def test_outil_appele_produit_une_preuve(registry_agents: AgentRegistry) -> None:
    llm = FauxLLM(
        tours=[
            {"tool_calls": [{"name": "web.search", "args": {"query": "prix cacao"}}]},
            {"content": "Le prix est de 2 500 FCFA/kg (source)."},
        ]
    )
    skills = FauxRegistry()
    result = await _runtime(registry_agents, llm, skills).execute(_task(), _scope())

    assert result.status == "completed"
    assert result.is_verified() is True
    assert result.evidence[0].reference == "https://example.org/source"
    assert result.tool_calls == 1
    assert skills.executes[0][0] == "web_research"


@pytest.mark.asyncio()
async def test_outil_non_autorise_refuse_sans_execution(registry_agents: AgentRegistry) -> None:
    llm = FauxLLM(
        tours=[
            {"tool_calls": [{"name": "code_exec", "args": {"code": "print(1)"}}]},
            {"content": "Je n'ai pas pu exécuter l'outil."},
        ]
    )
    skills = FauxRegistry()
    result = await _runtime(registry_agents, llm, skills).execute(_task(), _scope())

    assert skills.executes == []  # jamais exécuté
    assert result.status == "partial"  # aucune preuve
    assert "Aucun outil n'a produit de preuve" in " ".join(result.limitations)


@pytest.mark.asyncio()
async def test_plafond_d_appels_outils_arrete_la_tache(registry_agents: AgentRegistry) -> None:
    llm = FauxLLM(
        tours=[
            {
                "tool_calls": [
                    {"name": "web.search", "args": {"query": "a"}},
                    {"name": "web.search", "args": {"query": "b"}},
                ]
            }
        ]
    )
    result = await _runtime(registry_agents, llm, FauxRegistry()).execute(
        _task(max_tool_calls=1), _scope()
    )

    assert result.status == "failed"
    assert "plafond" in result.summary.lower()
    assert result.tool_calls == 1  # le second appel n'a pas eu lieu


@pytest.mark.asyncio()
async def test_sans_outil_appele_le_resultat_nest_pas_complete(registry_agents: AgentRegistry) -> None:
    llm = FauxLLM(tours=[{"content": "Voici une réponse sans source."}])
    result = await _runtime(registry_agents, llm, FauxRegistry()).execute(_task(), _scope())

    assert result.status == "partial"
    assert result.is_verified() is False

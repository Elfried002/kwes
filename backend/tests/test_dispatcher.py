"""Dispatcher : plan validé, dépendances, parallélisme, idempotence."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.contracts import AgentResult, Evidence
from app.agents.dispatcher import CoreDispatcher, PlanError
from app.agents.registry import AgentRegistry
from app.db.models import AgentTask as AgentTaskRow
from app.db.models import Task

PACKAGE = Path(__file__).resolve().parents[2] / "docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1"


class FauxLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def chat(self, messages, *, json_mode=False, **kwargs):  # noqa: ANN001
        from app.agent.llm import LLMResult
        import json

        return LLMResult(content=json.dumps(self.payload), model="faux")


class FauxRuntime:
    """Runtime factice : enregistre l'ordre d'exécution."""

    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.ordre: list[str] = []
        self.results = results or {}

    async def execute(self, task, scope, *, context=()):  # noqa: ANN001
        self.ordre.append(task.agent_id)
        statut = self.results.get(task.agent_id, "completed")
        return AgentResult(
            task_id=task.task_id,
            mission_id=task.mission_id,
            agent_id=task.agent_id,
            status=statut,
            summary=f"{task.agent_id} a terminé",
            evidence=[Evidence(kind="source", reference="https://example.org")],
        )


def _mission(goal: str = "Veille sur le prix du cacao") -> Any:  # noqa: ANN401
    return SimpleNamespace(id=uuid.uuid4(), goal=goal)


@pytest.fixture()
def agents() -> AgentRegistry:
    if not PACKAGE.exists():
        pytest.skip("package agentique absent")
    return AgentRegistry(PACKAGE).load()


def _dispatcher(agents: AgentRegistry, payload: dict, runtime=None) -> CoreDispatcher:  # noqa: ANN001
    return CoreDispatcher(
        settings=SimpleNamespace(),
        db=None,
        agents=agents,
        runtime=runtime or FauxRuntime(),
        llm=FauxLLM(payload),
    )


@pytest.mark.asyncio()
async def test_plan_refuse_un_specialiste_inconnu(agents: AgentRegistry) -> None:
    dispatcher = _dispatcher(
        agents, {"tasks": [{"agent_id": "kwes.fantome", "objective": "x", "tools": []}]}
    )
    catalogue = [{"agent_id": "kwes.research", "nom": "Research", "outils": ["web.search"]}]
    with pytest.raises(PlanError, match="Spécialiste inconnu"):
        await dispatcher.propose_plan(_mission(), catalogue)


@pytest.mark.asyncio()
async def test_plan_ne_garde_que_les_outils_autorises(agents: AgentRegistry) -> None:
    dispatcher = _dispatcher(
        agents,
        {
            "tasks": [
                {
                    "agent_id": "kwes.research",
                    "objective": "Chercher le prix",
                    "expected_output": "Prix",
                    "tools": ["code_exec", "web.search"],
                }
            ]
        },
    )
    catalogue = [{"agent_id": "kwes.research", "nom": "Research", "outils": ["web.search"]}]
    plan = await dispatcher.propose_plan(_mission(), catalogue)

    assert plan[0].tools == ["web.search"]  # code_exec écarté


@pytest.mark.asyncio()
async def test_plan_vide_replie_sur_un_mono_agent(agents: AgentRegistry) -> None:
    """Un plan illisible ne fabrique pas d'étapes : une seule tâche est confiée
    au premier spécialiste disponible, et le journal le signale."""
    dispatcher = _dispatcher(agents, {"tasks": []})
    catalogue = [{"agent_id": "kwes.research", "nom": "Research", "outils": ["web.search"]}]
    plan = await dispatcher.propose_plan(_mission(), catalogue)

    assert len(plan) == 1
    assert plan[0].agent_id == "kwes.research"
    assert plan[0].objective


@pytest.mark.asyncio()
async def test_plan_accepte_un_emballage_different(agents: AgentRegistry) -> None:
    """Le modèle peut répondre {"plan": [...]} : on l'accepte."""
    dispatcher = _dispatcher(
        agents,
        {"plan": [{"agent_id": "kwes.research", "objective": "Veille cacao", "tools": ["web.search"]}]},
    )
    catalogue = [{"agent_id": "kwes.research", "nom": "Research", "outils": ["web.search"]}]
    plan = await dispatcher.propose_plan(_mission(), catalogue)
    assert len(plan) == 1


@pytest.mark.asyncio()
async def test_graphe_respecte_les_dependances(client, app, settings, user_id) -> None:  # noqa: ANN001
    """B dépend de A : B ne démarre qu'après la fin de A."""
    from app.core.tenancy import ensure_personal_tenant
    from app.core.security import CurrentUser

    async with app.state.db.session() as session:
        await ensure_personal_tenant(
            session,
            CurrentUser(id=user_id, email="ada@kwes.local", display_name="Ada", locale="fr"),
        )
        mission = Task(
            tenant_id=user_id,
            user_id=user_id,
            title="Test",
            goal="Chaîne A puis B",
            status="queued",
        )
        session.add(mission)
        await session.commit()
        mission_id = mission.id

    runtime = FauxRuntime()
    dispatcher = CoreDispatcher(
        settings=settings,
        db=app.state.db,
        agents=AgentRegistry(PACKAGE).load(),
        runtime=runtime,
        llm=FauxLLM({"tasks": []}),
    )

    from app.agents.dispatcher import PlanItem

    items = [
        PlanItem("kwes.research", "Tâche A : collecter les sources", "sortie A", [], [], ["web.search"]),
        PlanItem("kwes.research", "Tâche B : synthétiser", "sortie B", [], [0], ["web.search"]),
    ]
    async with app.state.db.session() as session:
        mission = await session.get(Task, mission_id)
        rows = await dispatcher._save_plan(mission, items, user_id)

    assert rows[0].depends_on == []
    assert rows[1].depends_on == [rows[0].idempotency_key]

    faits = await dispatcher._execute_graph(
        rows, tenant_id=user_id, user_id=user_id, journal=None
    )
    assert runtime.ordre == ["kwes.research", "kwes.research"]
    assert all(f["status"] == "completed" for f in faits.values())


@pytest.mark.asyncio()
async def test_plan_idempotent_ne_duplique_pas(client, app, settings, user_id) -> None:  # noqa: ANN001
    from app.core.tenancy import ensure_personal_tenant
    from app.core.security import CurrentUser

    async with app.state.db.session() as session:
        await ensure_personal_tenant(
            session,
            CurrentUser(id=user_id, email="ada@kwes.local", display_name="Ada", locale="fr"),
        )
        mission = Task(tenant_id=user_id, user_id=user_id, title="T", goal="G", status="queued")
        session.add(mission)
        await session.commit()
        mission_id = mission.id

    dispatcher = CoreDispatcher(
        settings=settings,
        db=app.state.db,
        agents=AgentRegistry(PACKAGE).load(),
        runtime=FauxRuntime(),
        llm=FauxLLM({"tasks": []}),
    )
    from app.agents.dispatcher import PlanItem

    items = [PlanItem("kwes.research", "Tâche unique de veille", "sortie", [], [], ["web.search"])]
    async with app.state.db.session() as session:
        mission = await session.get(Task, mission_id)
        await dispatcher._save_plan(mission, items, user_id)
    async with app.state.db.session() as session:
        mission = await session.get(Task, mission_id)
        await dispatcher._save_plan(mission, items, user_id)
        from sqlalchemy import func, select

        total = (
            await session.execute(
                select(func.count()).select_from(AgentTaskRow).where(
                    AgentTaskRow.mission_id == mission_id
                )
            )
        ).scalar()
    assert total == 1

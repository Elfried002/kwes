"""Service de missions : démarrage contrôlé, contexte RLS, suivi d'exécution.

Le dispatcher tourne dans une tâche asyncio du processus API (staging). Chaque
course repose l'identité du demandeur avant d'ouvrir la moindre session : les
requêtes émises par les outils et le journal restent soumises à la RLS.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from app.agents.dispatcher import CoreDispatcher
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agent.llm import GeminiTextClient
from app.core.config import Settings
from app.db.models import AgentTask, RunEvent, Task
from app.db.rls import set_rls_user
from app.core.tenancy import set_current_tenant
from app.skills.registry import SkillRegistry

logger = logging.getLogger("kwes.agents.service")


def build_dispatcher(
    *,
    settings: Settings,
    db: Any,
    registry: SkillRegistry,
    llm: Any,
    fetcher: Any,
    package_root: Any,
) -> CoreDispatcher:
    agents = AgentRegistry(package_root).load()
    runtime = AgentRuntime(
        settings=settings, agents=agents, skills=registry, llm=llm, fetcher=fetcher
    )
    return CoreDispatcher(settings=settings, db=db, agents=agents, runtime=runtime, llm=llm)


class MissionService:
    """Démarre et suit les missions ; un seul runner par mission."""

    def __init__(self, dispatcher: CoreDispatcher, db: Any) -> None:
        self.dispatcher = dispatcher
        self.db = db
        self._running: dict[uuid.UUID, asyncio.Task] = {}

    @property
    def running(self) -> int:
        return len([t for t in self._running.values() if not t.done()])

    def start(self, mission_id: uuid.UUID, *, user_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        if mission_id in self._running and not self._running[mission_id].done():
            return False
        self._running[mission_id] = asyncio.create_task(
            self._run(mission_id, user_id=user_id, tenant_id=tenant_id),
            name=f"mission-{mission_id}",
        )
        return True

    async def _run(self, mission_id: uuid.UUID, *, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        # Contexte posé avant toute session : le pool applique les claims.
        set_rls_user(user_id)
        set_current_tenant(tenant_id)
        try:
            await self.dispatcher.run(mission_id)
        except Exception:  # noqa: BLE001 - déjà journalisé par le dispatcher
            logger.exception("Mission %s terminée en erreur", mission_id)
        finally:
            set_rls_user(None)
            self._running.pop(mission_id, None)

    async def wait(self, mission_id: uuid.UUID, timeout: float = 300.0) -> None:
        tache = self._running.get(mission_id)
        if tache is not None:
            try:
                await asyncio.wait_for(asyncio.shield(tache), timeout)
            except asyncio.TimeoutError:
                logger.warning("Mission %s toujours en cours après %.0f s", mission_id, timeout)


async def mission_snapshot(db: Any, mission_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any] | None:
    """Vue complète d'une mission : tâches déléguées et derniers événements."""
    async with db.session() as session:
        mission = await session.get(Task, mission_id)
        if mission is None or mission.user_id != user_id:
            return None
        taches = (
            await session.execute(
                select(AgentTask)
                .where(AgentTask.mission_id == mission_id)
                .order_by(AgentTask.seq)
            )
        ).scalars().all()
        evenements = (
            await session.execute(
                select(RunEvent)
                .where(RunEvent.mission_id == mission_id)
                .order_by(RunEvent.occurred_at.desc())
                .limit(80)
            )
        ).scalars().all()

    return {
        "id": str(mission.id),
        "title": mission.title,
        "goal": mission.goal,
        "status": mission.status,
        "progress": mission.progress,
        "summary": mission.result_summary,
        "error_code": mission.error_code,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        "tasks": [
            {
                "id": str(t.id),
                "agent_id": t.agent_id,
                "objective": t.objective,
                "status": t.status,
                "attempt": t.attempt,
                "tools": t.allowed_tools,
                "summary": t.result_summary,
                "evidence": t.evidence,
                "limitations": t.limitations,
                "error_code": t.error_code,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            }
            for t in taches
        ],
        "events": [
            {
                "type": e.event_type,
                "status": e.status,
                "agent_id": e.agent_id,
                "tool_id": e.tool_id,
                "duration_ms": e.duration_ms,
                "error_code": e.error_code,
                "at": e.occurred_at.isoformat() if e.occurred_at else None,
                "metadata": e.safe_metadata,
            }
            for e in reversed(evenements)
        ],
    }

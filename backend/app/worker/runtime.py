"""Composition du runtime : API et worker partagent la même fabrique.

Objectif P0 : une seule façon de construire la base, le registre, la file, le
LLM et l'orchestrateur. L'API ne s'en sert que pour les requêtes, le worker que
pour l'exécution. Aucune logique métier n'est dupliquée : on réutilise
``build_orchestrator`` et le registre existants.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agent.orchestrator import Orchestrator, build_orchestrator
from app.core.config import Settings
from app.db.base import Database
from app.skills.registry import SkillRegistry
from app.skills.render import make_browser_fetcher
from app.worker.queue import TaskQueue, build_queue

logger = logging.getLogger("kwes.runtime")

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Runtime:
    settings: Settings
    db: Database
    registry: SkillRegistry
    queue: TaskQueue
    orchestrator: Orchestrator
    # Connexion système réservée à la gestion de file (claim, reprise). Elle ne
    # sert jamais à lire les données d'une mission : l'exécution passe par `db`,
    # avec le rôle applicatif et le contexte du tenant de la tâche.
    db_system: Database | None = None

    async def aclose(self) -> None:
        await self.queue.close()
        await self.db.dispose()
        if self.db_system is not None and self.db_system is not self.db:
            await self.db_system.dispose()


async def build_runtime(
    settings: Settings,
    *,
    fetcher: Any | None = None,
    with_queue: bool = True,
) -> Runtime:
    """Construit les composants partagés par l'API et le worker."""
    # `rls=True` installe l'écouteur de pool : chaque connexion empruntée reçoit
    # l'identité de la tâche en cours, y compris après un commit. Sans cela, les
    # écritures de fin de mission (notifications) sont refusées par la politique.
    db = Database(
        settings.effective_database_url,
        pool_size=settings.database_pool_size,
        rls=settings.db_rls_enabled and not settings.db_rls_bypass,
    )
    # Quand la RLS est active pour l'application, la gestion de file a besoin
    # d'une vue système (claim/sweep). Elle est séparée de la connexion
    # d'exécution, qui reste soumise aux politiques.
    db_system: Database | None = None
    if settings.db_rls_enabled and not settings.db_rls_bypass:
        db_system = Database(settings.database_url, pool_size=2)

    registry = SkillRegistry(SKILLS_DIR, settings)
    registry.load()

    if fetcher is None:
        fetcher = make_browser_fetcher(settings.browser_domain_allowlist, settings)

    queue: TaskQueue
    if with_queue:
        queue = await build_queue(settings)
    else:  # pragma: no cover - réservé aux tests unitaires
        from app.worker.queue import MemoryTaskQueue

        queue = MemoryTaskQueue()

    orchestrator = build_orchestrator(
        settings=settings,
        db=db,
        registry=registry,
        queue=queue,
        fetcher=fetcher,
    )
    logger.info(
        "Runtime prêt (queue=%s, db=%s, skills=%s)",
        queue.backend,
        "sqlite" if "sqlite" in settings.database_url else "postgres",
        len(registry.manifests()),
    )
    # Le worker amorce la lecture d'une tâche via la connexion système, puis
    # exécute sous RLS : l'orchestrateur a besoin des deux.
    if db_system is not None:
        orchestrator.system_db = db_system  # type: ignore[attr-defined]

    return Runtime(
        settings=settings,
        db=db,
        registry=registry,
        queue=queue,
        orchestrator=orchestrator,
        db_system=db_system,
    )

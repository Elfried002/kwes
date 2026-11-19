"""Application FastAPI Kwes — point d'entrée.

Lancement : uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, update

from app.agent.llm import GeminiTextClient
from app.agent.orchestrator import build_orchestrator
from app.agent.voice import build_voice_provider
from app.api import (
    admin,
    approvals,
    chat,
    connectors,
    conversations,
    missions,
    dev,
    devices,
    documents,
    evidence,
    health,
    memory,
    notifications,
    skills,
    tasks,
    tenants,
    voice,
    voice_live,
)
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import KwesHttpMiddleware
from app.core.rate_limit import SlidingWindowLimiter, enforce_rate_limit
from app.db.base import Database
from app.db.models import Skill, SkillVersion
from app.core.utils import utcnow
from app.skills.fetch import make_fetcher
from app.skills.render import make_browser_fetcher, render_available
from app.skills.registry import SkillRegistry
from app.worker.queue import build_queue
from app.worker.worker import TaskWorker
from app.ws import router as ws_router

logger = logging.getLogger("kwes")

SKILLS_DIR = Path(__file__).resolve().parent / "skills"


async def seed_skills(db: Database, registry: SkillRegistry) -> None:
    """Synchronise la table `skills` avec les manifestes chargés."""
    async with db.session() as session:
        existing = {
            row.name: row for row in (await session.execute(select(Skill))).scalars().all()
        }
        for manifest in registry.manifests():
            row = existing.get(manifest["name"])
            if row is None:
                row = Skill(
                    name=manifest["name"],
                    description=manifest["description"],
                    current_version=manifest["version"],
                    enabled=True,
                )
                session.add(row)
                await session.flush()
                session.add(
                    SkillVersion(
                        skill_id=row.id,
                        version=manifest["version"],
                        manifest_json=manifest,
                        artifact_hash=manifest["artifact_hash"],
                        status="active",
                        approved_at=utcnow(),
                    )
                )
                logger.info("Skill enregistré: %s v%s", manifest["name"], manifest["version"])
            else:
                row.description = manifest["description"]
                row.current_version = manifest["version"]
                row.enabled = True
                version_row = (
                    await session.execute(
                        select(SkillVersion).where(
                            SkillVersion.skill_id == row.id,
                            SkillVersion.version == manifest["version"],
                        )
                    )
                ).scalar_one_or_none()
                if version_row is None:
                    # Une seule version active par skill (contrainte en base) :
                    # l'ancienne est conservée mais rétrogradée avant insertion.
                    await session.execute(
                        update(SkillVersion)
                        .where(
                            SkillVersion.skill_id == row.id,
                            SkillVersion.status == "active",
                        )
                        .values(status="deprecated")
                    )
                    session.add(
                        SkillVersion(
                            skill_id=row.id,
                            version=manifest["version"],
                            manifest_json=manifest,
                            artifact_hash=manifest["artifact_hash"],
                            status="active",
                            approved_at=utcnow(),
                        )
                    )
        await session.commit()


async def _mission_sweeper(application: Any, settings: Any) -> None:
    """Reprend les missions dont le processus a disparu.

    Lecture par une connexion système (les missions n'ont pas d'identité dans ce
    contexte) ; l'exécution, elle, repose le contexte du demandeur.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from app.db.base import Database
    from app.db.models import Task, utcnow

    system_db = Database(settings.database_url, pool_size=2)
    try:
        while True:
            await asyncio.sleep(max(30, settings.mission_sweeper_interval_seconds))
            service = getattr(application.state, "missions", None)
            if service is None:
                continue
            try:
                seuil = utcnow() - timedelta(seconds=settings.mission_sweeper_stale_seconds)
                async with system_db.session() as session:
                    orphelines = (
                        await session.execute(
                            select(Task)
                            .where(Task.status.in_(("queued", "running")), Task.updated_at < seuil)
                            .limit(2)
                        )
                    ).scalars().all()
                for mission in orphelines:
                    logger.warning("Reprise de la mission interrompue %s", mission.id)
                    service.start(
                        mission.id,
                        user_id=mission.user_id,
                        tenant_id=mission.tenant_id or mission.user_id,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Balayage des missions impossible")
    finally:
        await system_db.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if settings.sentry_dsn:
        try:
            import sentry_sdk  # type: ignore[import-not-found]

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.sentry_environment or settings.app_env,
                traces_sample_rate=0.05,
                send_default_pii=False,
            )
            logger.info("Sentry activé (environnement %s).", settings.sentry_environment or settings.app_env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sentry non initialisé : %s", exc)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        db: Database = application.state.db
        await db.create_all()
        registry: SkillRegistry = application.state.registry
        await seed_skills(db, registry)

        # Catalogue des connecteurs : aligné sur les manifestes du dépôt.
        from app.connectors.catalog import sync_catalog

        racine_connecteurs = Path(settings.connectors_dir)
        if not racine_connecteurs.is_absolute():
            racine_connecteurs = Path(__file__).resolve().parents[2] / settings.connectors_dir
        try:
            await sync_catalog(db, racine_connecteurs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Synchronisation du catalogue de connecteurs impossible : %s", exc)

        queue = await build_queue(settings)
        application.state.queue = queue
        llm = GeminiTextClient(settings)
        application.state.llm = llm
        orchestrator = build_orchestrator(
            settings=settings,
            db=db,
            registry=registry,
            queue=queue,
            llm=llm,
            fetcher=application.state.fetcher,
        )
        application.state.orchestrator = orchestrator

        # Dispatcher agentique : plan → spécialistes → résultats consolidés.
        # Un package absent ne doit pas empêcher l'API de servir le chat :
        # on désactive les missions et on le dit clairement.
        from app.agents.service import MissionService, build_dispatcher

        try:
            dispatcher = build_dispatcher(
                settings=settings,
                db=db,
                registry=registry,
                llm=llm,
                fetcher=application.state.fetcher,
                package_root=Path(settings.agents_package_root),
            )
            application.state.missions = MissionService(dispatcher, db)
            if settings.mission_sweeper_enabled:
                application.state.sweeper = asyncio.create_task(
                    _mission_sweeper(application, settings)
                )
            logger.info(
                "Dispatcher agentique prêt (%s agents).",
                len(dispatcher.agents.all()),
            )
        except Exception as exc:  # noqa: BLE001
            application.state.missions = None
            logger.warning("Dispatcher agentique indisponible : %s", exc)

        # P0 : le worker vit dans son propre processus (service kwes-worker).
        # L'API ne le démarre que si on le demande explicitement (tests, dev).
        worker: TaskWorker | None = None
        if settings.worker_inline:
            worker = TaskWorker(
                settings=settings, db=db, orchestrator=orchestrator, queue=queue
            )
            await worker.start()
            logger.info("Worker inline activé (dev/tests).")
        application.state.worker = worker
        if settings.llm_is_mock:
            logger.warning(
                "MODE HORS LIGNE : aucune clé Gemini, réponses simulées et en-tête X-Kwes-Mock: 1."
            )
        try:
            yield
        finally:
            sweeper = getattr(application.state, "sweeper", None)
            if sweeper is not None:
                sweeper.cancel()
            if worker is not None:
                await worker.stop()
            await db.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.db = Database(
        settings.effective_database_url,
        pool_size=settings.database_pool_size,
        rls=settings.db_rls_enabled and not settings.db_rls_bypass,
    )
    app.state.rate_limiter = SlidingWindowLimiter()
    registry = SkillRegistry(SKILLS_DIR, settings)
    registry.load()
    app.state.registry = registry
    # Rendu Chromium quand Playwright est disponible, repli httpx sinon.
    app.state.fetcher = make_browser_fetcher(settings.browser_domain_allowlist, settings)
    logger.info("Fetcher des skills : rendu Chromium=%s (mode=%s)", render_available(), settings.browser_render)
    app.state.voice = build_voice_provider(settings)

    app.add_middleware(KwesHttpMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Kwes-Mock",
            "X-Kwes-Mock-Providers",
            "X-Request-ID",
            "X-Total-Count",
            # Sans cela le navigateur masque le nom du fichier téléchargé.
            "Content-Disposition",
        ],
        max_age=600,
    )

    register_exception_handlers(app)

    # Health : public, sans préfixe ET sous /api/v1 (contrat).
    app.include_router(health.router)
    app.include_router(health.router, prefix=settings.api_prefix)

    private_deps = [Depends(enforce_rate_limit)]
    prefix = settings.api_prefix
    app.include_router(chat.router, prefix=prefix, dependencies=private_deps)
    app.include_router(conversations.router, prefix=prefix, dependencies=private_deps)
    app.include_router(tasks.router, prefix=prefix, dependencies=private_deps)
    app.include_router(skills.router, prefix=prefix, dependencies=private_deps)
    app.include_router(memory.router, prefix=prefix, dependencies=private_deps)
    app.include_router(documents.router, prefix=prefix, dependencies=private_deps)
    app.include_router(evidence.router, prefix=prefix, dependencies=private_deps)
    app.include_router(approvals.router, prefix=prefix, dependencies=private_deps)
    app.include_router(notifications.router, prefix=prefix, dependencies=private_deps)
    app.include_router(voice.router, prefix=prefix, dependencies=private_deps)
    app.include_router(tenants.router, prefix=prefix, dependencies=private_deps)
    app.include_router(missions.router, prefix=prefix, dependencies=private_deps)
    app.include_router(connectors.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)
    app.include_router(voice_live.router, prefix=prefix)
    app.include_router(devices.router, prefix=prefix)
    if settings.app_env in ("dev", "test") and settings.dev_endpoints:
        app.include_router(dev.router, prefix=prefix)
    app.include_router(ws_router, prefix=prefix)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )

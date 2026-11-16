"""Application FastAPI Kwes — point d'entrée.

Lancement : uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.agent.deepseek import DeepSeekClient
from app.agent.orchestrator import build_orchestrator
from app.agent.voice import build_voice_provider
from app.api import (
    approvals,
    chat,
    conversations,
    dev,
    devices,
    health,
    memory,
    notifications,
    skills,
    tasks,
    voice,
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        db: Database = application.state.db
        await db.create_all()
        registry: SkillRegistry = application.state.registry
        await seed_skills(db, registry)

        queue = await build_queue(settings)
        application.state.queue = queue
        llm = DeepSeekClient(settings)
        application.state.llm = llm
        orchestrator = build_orchestrator(
            settings=settings, db=db, registry=registry, queue=queue, llm=llm
        )
        orchestrator.fetcher = application.state.fetcher
        application.state.orchestrator = orchestrator

        worker = TaskWorker(
            settings=settings, db=db, orchestrator=orchestrator, queue=queue
        )
        application.state.worker = worker
        await worker.start()
        if settings.llm_is_mock:
            logger.warning(
                "MODE MOCK : DeepSeek non configuré, réponses simulées et en-tête X-Kwes-Mock: 1."
            )
        try:
            yield
        finally:
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
    app.state.db = Database(settings.database_url, pool_size=settings.database_pool_size)
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
        expose_headers=["X-Kwes-Mock", "X-Kwes-Mock-Providers", "X-Request-ID", "X-Total-Count"],
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
    app.include_router(approvals.router, prefix=prefix, dependencies=private_deps)
    app.include_router(notifications.router, prefix=prefix, dependencies=private_deps)
    app.include_router(voice.router, prefix=prefix, dependencies=private_deps)
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

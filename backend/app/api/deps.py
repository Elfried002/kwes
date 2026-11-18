"""Dépendances FastAPI partagées (config, DB, orchestrateur, registre)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import Orchestrator
from app.core.config import Settings
from app.core.security import CurrentUser, get_current_user
from app.core.tenancy import TenantContext, get_tenant
from app.db.base import Database, get_session
from app.skills.registry import SkillRegistry


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.db


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def get_registry(request: Request) -> SkillRegistry:
    return request.app.state.registry


def get_voice_provider(request: Request) -> Any:
    return request.app.state.voice


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
OrchestratorDep = Annotated[Orchestrator, Depends(get_orchestrator)]
RegistryDep = Annotated[SkillRegistry, Depends(get_registry)]
VoiceDep = Annotated[Any, Depends(get_voice_provider)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
TenantDep = Annotated[TenantContext, Depends(get_tenant)]


class Pagination:
    def __init__(
        self,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> None:
        self.limit = limit
        self.offset = offset


PageDep = Annotated[Pagination, Depends(Pagination)]

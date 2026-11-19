"""API d'administration : agrégats, exploitation, audit.

Deux garanties :
  * chaque endpoint vérifie le rôle côté serveur (cacher un bouton ne protège rien) ;
  * les agrégats multi-tenant passent par une connexion d'exploitation dédiée,
    après contrôle du rôle, et ne renvoient que des métadonnées.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import SessionDep, SettingsDep, UserDep
from app.core.errors import Forbidden, NotFound
from app.db.base import Database
from app.db.models import (
    AdminAlert,
    AgentOverride,
    AuditLog,
    LLMUsage,
    PlatformRole,
    RunEvent,
    TenantQuota,
    Task,
    Tenant,
    TenantMembership,
)

logger = logging.getLogger("kwes.admin")

router = APIRouter(tags=["admin"], prefix="/admin")

ROLES = {
    "super_admin",
    "ops_admin",
    "support_readonly",
    "security_auditor",
    "billing_admin",
}


def _admin_db(request: Request) -> Database:
    """Connexion d'exploitation (rôle propriétaire), réservée à l'admin."""
    # Sous SQLite (tests), une seconde connexion sur le même fichier provoque
    # des verrous d'écriture : on réutilise la base de l'application.
    url = request.app.state.settings.database_url
    if url.startswith("sqlite"):
        return request.app.state.db
    cached = getattr(request.app.state, "admin_db", None)
    if cached is None:
        cached = Database(url, pool_size=2)
        request.app.state.admin_db = cached
    return cached


async def current_role(session: Any, user_id: uuid.UUID) -> str | None:
    ligne = await session.get(PlatformRole, user_id)
    return ligne.role if ligne is not None else None


def require_roles(*autorises: str) -> Callable[..., Any]:
    """Dépendance : refuse si le rôle de l'appelant n'est pas autorisé."""

    async def verifier(session: SessionDep, user: UserDep) -> str:
        role = await current_role(session, user.id)
        # On referme la transaction de lecture : l'opération admin ouvre ensuite
        # sa propre session d'exploitation, et sous SQLite une lecture non
        # refermée bloquait l'écriture qui suivait.
        await session.commit()
        if role is None:
            raise Forbidden("Accès réservé à l'administration.")
        if autorises and role not in autorises:
            raise Forbidden(f"Rôle {role} non autorisé pour cette opération.")
        return role

    return verifier


async def _audit(
    session: Any, *, actor: uuid.UUID, action: str, target: str, details: dict[str, Any]
) -> None:
    session.add(
        AuditLog(
            tenant_id=None,
            user_id=actor,
            actor_type="admin",
            actor_id=str(actor),
            action=action[:64],
            resource_type="admin",
            resource_id=target[:64],
            decision="allow",
            metadata_redacted=details,
        )
    )


@router.get("/overview")
async def overview(
    request: Request,
    session: SessionDep,
    user: UserDep,
    role: Annotated[str, Depends(require_roles(*ROLES))],
) -> dict[str, Any]:
    db = _admin_db(request)
    seuil = datetime.now(timezone.utc) - timedelta(days=30)
    async with db.session() as admin:
        tenants = (await admin.execute(select(func.count()).select_from(Tenant))).scalar() or 0
        users = (await admin.execute(select(func.count()).select_from(TenantMembership))).scalar() or 0
        missions = (await admin.execute(select(func.count()).select_from(Task))).scalar() or 0
        missions_30j = (
            await admin.execute(
                select(func.count()).select_from(Task).where(Task.created_at >= seuil)
            )
        ).scalar() or 0
        en_cours = (
            await admin.execute(
                select(func.count())
                .select_from(Task)
                .where(Task.status.in_(("queued", "planning", "running")))
            )
        ).scalar() or 0
        echouees = (
            await admin.execute(
                select(func.count()).select_from(Task).where(Task.status == "failed")
            )
        ).scalar() or 0
        runs = (await admin.execute(select(func.count()).select_from(RunEvent))).scalar() or 0
        alertes = (
            await admin.execute(
                select(func.count()).select_from(AdminAlert).where(AdminAlert.acknowledged_at.is_(None))
            )
        ).scalar() or 0
        usage = (
            await admin.execute(
                select(
                    func.coalesce(func.sum(LLMUsage.input_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.output_tokens), 0),
                    func.count(LLMUsage.id),
                )
            )
        ).one()

    return {
        "role": role,
        "environment": request.app.state.settings.app_env,
        "tenants": tenants,
        "members": users,
        "missions": {"total": missions, "last_30d": missions_30j, "running": en_cours, "failed": echouees},
        "agent_runs": runs,
        "alerts_open": alertes,
        "llm": {
            "calls": usage[2],
            "input_tokens": int(usage[0] or 0),
            "output_tokens": int(usage[1] or 0),
            # Aucun tarif validé : le coût reste inconnu, jamais zéro trompeur.
            "cost": None,
            "cost_currency": None,
        },
        "sentry": {
            "configured": bool(getattr(request.app.state.settings, "sentry_dsn", "")),
            "detail": "Aucun DSN configuré : aucune erreur n'est transmise."
            if not getattr(request.app.state.settings, "sentry_dsn", "")
            else "DSN configuré.",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/tenants")
async def tenants_list(
    request: Request,
    session: SessionDep,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin", "support_readonly", "security_auditor"))],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    db = _admin_db(request)
    async with db.session() as admin:
        lignes = (
            await admin.execute(
                select(Tenant).order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()
        items = []
        for tenant in lignes:
            membres = (
                await admin.execute(
                    select(func.count())
                    .select_from(TenantMembership)
                    .where(TenantMembership.tenant_id == tenant.id)
                )
            ).scalar() or 0
            missions = (
                await admin.execute(
                    select(func.count()).select_from(Task).where(Task.tenant_id == tenant.id)
                )
            ).scalar() or 0
            items.append(
                {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "kind": tenant.kind,
                    "members": membres,
                    "missions": missions,
                    "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
                }
            )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/missions")
async def missions_list(
    request: Request,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin", "support_readonly", "security_auditor"))],
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Métadonnées de missions, tous tenants. Aucun contenu privé."""
    db = _admin_db(request)
    requete = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if status:
        requete = requete.where(Task.status == status)
    async with db.session() as admin:
        lignes = (await admin.execute(requete)).scalars().all()
    return {
        "items": [
            {
                "id": str(t.id),
                "tenant_id": str(t.tenant_id) if t.tenant_id else None,
                "title": t.title[:120],
                "status": t.status,
                "error_code": t.error_code,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in lignes
        ]
    }


@router.get("/usage")
async def usage(
    request: Request,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin", "billing_admin", "security_auditor"))],
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    seuil = datetime.now(timezone.utc) - timedelta(days=days)
    db = _admin_db(request)
    async with db.session() as admin:
        par_modele = (
            await admin.execute(
                select(
                    LLMUsage.model,
                    LLMUsage.provider,
                    func.count(LLMUsage.id),
                    func.coalesce(func.sum(LLMUsage.input_tokens), 0),
                    func.coalesce(func.sum(LLMUsage.output_tokens), 0),
                    func.avg(LLMUsage.duration_ms),
                )
                .where(LLMUsage.created_at >= seuil)
                .group_by(LLMUsage.model, LLMUsage.provider)
            )
        ).all()
    return {
        "period_days": days,
        "models": [
            {
                "model": row[0],
                "provider": row[1],
                "calls": row[2],
                "input_tokens": int(row[3] or 0),
                "output_tokens": int(row[4] or 0),
                "avg_duration_ms": int(row[5] or 0),
                "cost": None,
            }
            for row in par_modele
        ],
        "cost_note": "Aucun barème validé : le coût monétaire reste inconnu.",
    }


@router.get("/alerts")
async def alerts(
    request: Request,
    role: Annotated[str, Depends(require_roles(*ROLES))],
    open_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    db = _admin_db(request)
    requete = select(AdminAlert).order_by(AdminAlert.created_at.desc()).limit(limit)
    if open_only:
        requete = requete.where(AdminAlert.acknowledged_at.is_(None))
    async with db.session() as admin:
        lignes = (await admin.execute(requete)).scalars().all()
    return {
        "items": [
            {
                "id": str(a.id),
                "severity": a.severity,
                "source": a.source,
                "code": a.code,
                "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in lignes
        ]
    }


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/missions/{mission_id}/cancel")
async def admin_cancel_mission(
    mission_id: uuid.UUID,
    payload: ReasonIn,
    request: Request,
    session: SessionDep,
    user: UserDep,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin"))],
) -> dict[str, Any]:
    db = _admin_db(request)
    async with db.session() as admin:
        mission = await admin.get(Task, mission_id)
        if mission is None:
            raise NotFound("Mission introuvable.")
        avant = mission.status
        mission.status = "cancelled"
        await admin.commit()
    await _audit(
        session,
        actor=user.id,
        action="admin.mission.cancel",
        target=str(mission_id),
        details={"role": role, "reason": payload.reason, "before": avant},
    )
    await session.commit()
    return {"id": str(mission_id), "status": "cancelled", "before": avant}


class SuspendIn(BaseModel):
    suspended: bool
    reason: str = Field(min_length=5, max_length=500)


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: uuid.UUID,
    payload: SuspendIn,
    request: Request,
    session: SessionDep,
    user: UserDep,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin"))],
) -> dict[str, Any]:
    db = _admin_db(request)
    async with db.session() as admin:
        tenant = await admin.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound("Espace introuvable.")
        tenant.suspended_at = datetime.now(timezone.utc) if payload.suspended else None
        tenant.suspended_reason = payload.reason if payload.suspended else None
        await admin.commit()
    await _audit(
        session,
        actor=user.id,
        action="admin.tenant.suspend" if payload.suspended else "admin.tenant.reactivate",
        target=str(tenant_id),
        details={"role": role, "reason": payload.reason},
    )
    await session.commit()
    return {"id": str(tenant_id), "suspended": payload.suspended}


class ToggleIn(BaseModel):
    enabled: bool
    reason: str = Field(min_length=5, max_length=500)


@router.get("/agents")
async def agents_list(
    request: Request,
    session: SessionDep,
    role: Annotated[str, Depends(require_roles(*ROLES))],
) -> dict[str, Any]:
    service = getattr(request.app.state, "missions", None)
    if service is None:
        return {"items": [], "detail": "Dispatcher indisponible."}
    db = _admin_db(request)
    async with db.session() as admin:
        lignes = (await admin.execute(select(AgentOverride))).scalars().all()
    etats = {ligne.agent_id: ligne.enabled for ligne in lignes}
    items = []
    for agent in service.dispatcher.agents.all():
        items.append(
            {
                "agent_id": agent.agent_id,
                "display_name": agent.config.display_name,
                "type": agent.config.agent_type,
                "status": agent.config.status,
                "tools": agent.executable_tools(),
                "enabled": etats.get(agent.agent_id, True),
            }
        )
    return {"items": items}


@router.post("/agents/{agent_id}/toggle")
async def toggle_agent(
    agent_id: str,
    payload: ToggleIn,
    request: Request,
    session: SessionDep,
    user: UserDep,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin"))],
) -> dict[str, Any]:
    db = _admin_db(request)
    async with db.session() as admin:
        ligne = await admin.get(AgentOverride, agent_id)
        if ligne is None:
            ligne = AgentOverride(agent_id=agent_id, enabled=payload.enabled)
            admin.add(ligne)
        ligne.enabled = payload.enabled
        ligne.reason = payload.reason
        ligne.updated_by = user.id
        ligne.updated_at = datetime.now(timezone.utc)
        await admin.commit()
    await _audit(
        session,
        actor=user.id,
        action="admin.agent.enable" if payload.enabled else "admin.agent.disable",
        target=agent_id,
        details={"role": role, "reason": payload.reason},
    )
    await session.commit()
    return {"agent_id": agent_id, "enabled": payload.enabled}


@router.get("/quotas/{tenant_id}")
async def tenant_quotas(
    tenant_id: uuid.UUID,
    request: Request,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin", "billing_admin"))],
) -> dict[str, Any]:
    db = _admin_db(request)
    async with db.session() as admin:
        quota = await admin.get(TenantQuota, tenant_id)
        if quota is None:
            from app.core import quotas as quota_service

            quota = await quota_service.get_or_create(admin, tenant_id)
    return {
        "tenant_id": str(tenant_id),
        "max_concurrent_missions": quota.max_concurrent_missions,
        "max_missions_per_day": quota.max_missions_per_day,
        "max_tool_calls_per_mission": quota.max_tool_calls_per_mission,
        "max_llm_tokens_per_month": quota.max_llm_tokens_per_month,
    }


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    user: UserDep,
    role: Annotated[str, Depends(require_roles("super_admin", "ops_admin", "security_auditor"))],
) -> dict[str, Any]:
    db = _admin_db(request)
    async with db.session() as admin:
        alerte = await admin.get(AdminAlert, alert_id)
        if alerte is None:
            raise NotFound("Alerte introuvable.")
        alerte.acknowledged_at = datetime.now(timezone.utc)
        alerte.acknowledged_by = user.id
        await admin.commit()
    return {"id": str(alert_id), "acknowledged": True}

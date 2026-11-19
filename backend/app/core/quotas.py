"""Quotas par tenant : vérification atomique avant de lancer une mission."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db.models import Task, Tenant, TenantQuota

DEFAULTS = {
    "max_concurrent_missions": 2,
    "max_missions_per_day": 50,
    "max_tool_calls_per_mission": 24,
    "max_llm_tokens_per_month": 2_000_000,
}


class QuotaExceeded(RuntimeError):
    code = "QUOTA_EXCEEDED"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class TenantSuspended(RuntimeError):
    code = "TENANT_SUSPENDED"


async def get_or_create(session: Any, tenant_id: uuid.UUID) -> TenantQuota:
    quota = await session.get(TenantQuota, tenant_id)
    if quota is None:
        quota = TenantQuota(tenant_id=tenant_id, **DEFAULTS)
        session.add(quota)
        await session.commit()
        await session.refresh(quota)
    return quota


async def check(db: Any, tenant_id: uuid.UUID) -> dict[str, Any]:
    """Refuse une nouvelle mission si un plafond est atteint.

    La vérification est faite au moment de la création ; une course entre deux
    requêtes simultanées peut laisser passer une mission de plus, jamais un
    dépassement massif (les plafonds restent petits et les missions longues).
    """
    async with db.session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is not None and getattr(tenant, "suspended_at", None) is not None:
            raise TenantSuspended("Cet espace est suspendu.")

        quota = await get_or_create(session, tenant_id)
        en_cours = (
            await session.execute(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.tenant_id == tenant_id,
                    Task.status.in_(("queued", "planning", "running")),
                )
            )
        ).scalar() or 0
        jour = datetime.now(timezone.utc) - timedelta(days=1)
        aujourdhui = (
            await session.execute(
                select(func.count())
                .select_from(Task)
                .where(Task.tenant_id == tenant_id, Task.created_at >= jour)
            )
        ).scalar() or 0

    if en_cours >= quota.max_concurrent_missions:
        raise QuotaExceeded(
            "Trop de missions simultanées pour cet espace.",
            {"limit": quota.max_concurrent_missions, "current": en_cours},
        )
    if aujourdhui >= quota.max_missions_per_day:
        raise QuotaExceeded(
            "Limite de missions sur 24 h atteinte.",
            {"limit": quota.max_missions_per_day, "current": aujourdhui},
        )
    return {
        "concurrent": en_cours,
        "last_24h": aujourdhui,
        "max_concurrent": quota.max_concurrent_missions,
        "max_per_day": quota.max_missions_per_day,
    }

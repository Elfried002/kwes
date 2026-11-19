"""Quotas, suspension d'espace et kill-switch d'agent."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import AgentOverride, AuditLog, Task, TenantMembership, TenantQuota


def _espace(factory, user_id):
    """Crée l'espace personnel et l'appartenance attendus par TenantDep."""
    from app.db.models import Tenant, TenantMembership

    with factory() as session:
        if session.get(Tenant, user_id) is None:
            session.add(Tenant(id=user_id, name="Espace test", plan="free"))
            session.commit()
        deja = session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == user_id, TenantMembership.user_id == user_id
            )
        ).scalars().first()
        if deja is None:
            session.add(TenantMembership(tenant_id=user_id, user_id=user_id, role="owner"))
            session.commit()


def test_quota_refuse_trop_de_missions_simultanees(client, headers, user_id, db_session_factory) -> None:
    _espace(db_session_factory, user_id)
    with db_session_factory() as session:
        session.merge(TenantQuota(tenant_id=user_id, max_concurrent_missions=1))
        session.add(Task(tenant_id=user_id, user_id=user_id, title="en cours", goal="g", status="running"))
        session.commit()

    reponse = client.post("/api/v1/missions", json={"objective": "Une nouvelle mission"}, headers=headers)
    assert reponse.status_code == 422, reponse.text
    assert "simultan" in reponse.json()["error"]["message"].lower()


def test_espace_suspendu_refuse_les_missions(app, user_id, db_session_factory) -> None:
    """La vérification de quota refuse un espace suspendu (unité)."""
    import asyncio
    from datetime import datetime, timezone

    from app.core import quotas
    from app.db.models import Tenant, TenantMembership

    with db_session_factory() as session:
        if session.get(Tenant, user_id) is None:
            session.add(Tenant(id=user_id, name="Espace test", plan="free"))
            session.commit()
        deja = session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == user_id, TenantMembership.user_id == user_id
            )
        ).scalars().first()
        if deja is None:
            session.add(TenantMembership(tenant_id=user_id, user_id=user_id, role="owner"))
        tenant = session.get(Tenant, user_id)
        tenant.suspended_at = datetime.now(timezone.utc)
        session.commit()

    async def _run():
        with pytest.raises(quotas.TenantSuspended):
            await quotas.check(app.state.db, user_id)

    asyncio.run(_run())


def test_suspension_admin_auditee(client, headers, user_id, grant_role, db_session_factory) -> None:
    grant_role(user_id, "ops_admin")
    _espace(db_session_factory, user_id)
    reponse = client.post(
        f"/api/v1/admin/tenants/{user_id}/suspend",
        json={"suspended": True, "reason": "impayé constaté"},
        headers=headers,
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["suspended"] is True

    with db_session_factory() as session:
        lignes = session.execute(
            select(AuditLog).where(AuditLog.action == "admin.tenant.suspend")
        ).scalars().all()
    assert lignes


def test_killswitch_agent(client, headers, user_id, grant_role, db_session_factory) -> None:
    grant_role(user_id, "ops_admin")
    reponse = client.post(
        "/api/v1/admin/agents/kwes.research/toggle",
        json={"enabled": False, "reason": "incident en cours d'analyse"},
        headers=headers,
    )
    assert reponse.status_code == 200, reponse.text

    with db_session_factory() as session:
        ligne = session.get(AgentOverride, "kwes.research")
    assert ligne is not None and ligne.enabled is False

    liste = client.get("/api/v1/admin/agents", headers=headers)
    assert liste.status_code == 200
    research = next(a for a in liste.json()["items"] if a["agent_id"] == "kwes.research")
    assert research["enabled"] is False


def test_lecture_seule_ne_peut_pas_suspendre(client, headers, user_id, grant_role, db_session_factory) -> None:
    grant_role(user_id, "support_readonly")
    _espace(db_session_factory, user_id)
    reponse = client.post(
        f"/api/v1/admin/tenants/{user_id}/suspend",
        json={"suspended": True, "reason": "tentative non autorisée"},
        headers=headers,
    )
    assert reponse.status_code == 403


def test_cout_et_sentry_ne_sont_pas_inventes(client, headers, user_id, grant_role) -> None:
    grant_role(user_id, "super_admin")
    corps = client.get("/api/v1/admin/overview", headers=headers).json()
    assert corps["llm"]["cost"] is None
    assert corps["sentry"]["configured"] is False
    assert "Aucun DSN" in corps["sentry"]["detail"]

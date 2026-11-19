"""Cockpit admin : RBAC réel, agrégats, audit des actions sensibles."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, PlatformRole, Task


@pytest.fixture()
def grant_role(app, db_session_factory):
    def _grant(user_id: uuid.UUID, role: str) -> None:
        with db_session_factory() as session:
            session.merge(PlatformRole(user_id=user_id, role=role))
            session.commit()

    return _grant


def test_sans_role_acces_refuse(client, headers) -> None:
    for chemin in ("/api/v1/admin/overview", "/api/v1/admin/tenants", "/api/v1/admin/usage"):
        reponse = client.get(chemin, headers=headers)
        assert reponse.status_code == 403, (chemin, reponse.text)


def test_role_super_admin_ouvre_la_vue_globale(client, headers, user_id, grant_role) -> None:
    grant_role(user_id, "super_admin")
    reponse = client.get("/api/v1/admin/overview", headers=headers)
    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()

    assert corps["role"] == "super_admin"
    assert corps["tenants"] >= 0  # aucun tenant n'est créé tant qu'il n'est pas demandé
    assert corps["missions"]["total"] >= 0
    # Aucun tarif validé : le coût reste inconnu, jamais 0.
    assert corps["llm"]["cost"] is None
    assert "input_tokens" in corps["llm"]


def test_role_lecture_seule_ne_peut_pas_annuler(
    client, headers, user_id, grant_role, db_session_factory
) -> None:
    grant_role(user_id, "support_readonly")
    with db_session_factory() as session:
        tache = Task(
            tenant_id=user_id, user_id=user_id, title="À annuler", goal="Objectif", status="running"
        )
        session.add(tache)
        session.commit()
        mission_id = str(tache.id)
        session.close()
    reponse = client.post(
        f"/api/v1/admin/missions/{mission_id}/cancel",
        json={"reason": "test de rôle insuffisant"},
        headers=headers,
    )
    assert reponse.status_code == 403


def test_annulation_admin_auditee(client, headers, user_id, grant_role, db_session_factory) -> None:
    grant_role(user_id, "ops_admin")
    with db_session_factory() as session:
        tache = Task(
            tenant_id=user_id, user_id=user_id, title="À annuler", goal="Objectif", status="running"
        )
        session.add(tache)
        session.commit()
        mission_id = str(tache.id)
        session.close()
    reponse = client.post(
        f"/api/v1/admin/missions/{mission_id}/cancel",
        json={"reason": "mission bloquée depuis 2 heures"},
        headers=headers,
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["status"] == "cancelled"

    with db_session_factory() as session:
        lignes = session.execute(
            select(AuditLog).where(AuditLog.action == "admin.mission.cancel")
        ).scalars().all()
    assert lignes, "l'action sensible doit produire un événement d'audit"
    assert lignes[0].decision == "allow"


def test_usage_ne_fabrique_pas_de_cout(client, headers, user_id, grant_role) -> None:
    grant_role(user_id, "billing_admin")
    reponse = client.get("/api/v1/admin/usage?days=7", headers=headers)
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["cost_note"].startswith("Aucun barème validé")
    for modele in corps["models"]:
        assert modele["cost"] is None

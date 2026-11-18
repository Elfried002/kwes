"""Espaces de travail (tenants) : lecture, création, membres, paramètres.

L'isolation est garantie à deux niveaux : ces routes vérifient l'appartenance
et le rôle, et les politiques RLS de la base appliquent la même règle pour
toute requête qui contournerait l'API.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from app.api.deps import SessionDep, TenantDep, UserDep
from app.core.errors import NotFound, ValidationFailed
from app.core.tenancy import WRITE_ROLES, TenantContext, ensure_personal_tenant, tenant_settings
from app.db.models import Tenant, TenantMembership, TenantSettings

router = APIRouter(tags=["tenants"])

ROLES = ("owner", "admin", "member", "viewer")


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)


class MemberInvite(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: str = Field(default="member", max_length=16)


class MemberUpdate(BaseModel):
    role: str = Field(max_length=16)


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "espace"
    return f"{base[:48]}-{uuid.uuid4().hex[:6]}"


def tenant_dict(tenant: Tenant, membership: TenantMembership, *, members: int | None = None) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan,
        "role": membership.role,
        "is_personal": tenant.id == membership.user_id,
        "members": members,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


@router.get("/tenants")
async def list_tenants(user: UserDep, session: SessionDep, response: Response) -> list[dict[str, Any]]:
    """Espaces de l'utilisateur. L'espace personnel est créé à la première visite."""
    rows = (
        await session.execute(
            select(Tenant, TenantMembership)
            .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
            .where(TenantMembership.user_id == user.id)
            .order_by(Tenant.created_at.asc())
        )
    ).all()

    if not rows:
        await ensure_personal_tenant(session, user)
        rows = (
            await session.execute(
                select(Tenant, TenantMembership)
                .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
                .where(TenantMembership.user_id == user.id)
                .order_by(Tenant.created_at.asc())
            )
        ).all()

    counts = dict(
        (
            await session.execute(
                select(TenantMembership.tenant_id, func.count(TenantMembership.id))
                .where(TenantMembership.tenant_id.in_([t.id for t, _ in rows]))
                .group_by(TenantMembership.tenant_id)
            )
        ).all()
    )
    response.headers["X-Total-Count"] = str(len(rows))
    return [tenant_dict(t, m, members=int(counts.get(t.id, 0))) for t, m in rows]


@router.get("/tenants/current")
async def current_tenant(tenant: TenantDep, session: SessionDep) -> dict[str, Any]:
    settings = await tenant_settings(session, tenant.id)
    await session.commit()
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "role": tenant.role,
        "is_personal": tenant.is_personal,
        "can_write": tenant.can_write,
        "can_manage": tenant.can_manage,
        "settings": {
            "locale": settings.locale,
            "timezone": settings.timezone,
            "voice_language": settings.voice_language,
        },
    }


@router.post("/tenants", status_code=201)
async def create_tenant(payload: TenantCreate, user: UserDep, session: SessionDep) -> dict[str, Any]:
    await ensure_personal_tenant(session, user)
    tenant = Tenant(name=payload.name.strip(), slug=_slug(payload.name), plan="free")
    session.add(tenant)
    await session.flush()
    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role="owner")
    session.add(membership)
    session.add(TenantSettings(tenant_id=tenant.id))
    await session.commit()
    return tenant_dict(tenant, membership, members=1)


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: uuid.UUID, payload: TenantUpdate, tenant: TenantDep, session: SessionDep
) -> dict[str, Any]:
    if tenant.id != tenant_id or not tenant.can_manage:
        raise NotFound("Espace de travail introuvable.")
    row = await session.get(Tenant, tenant_id)
    if row is None:
        raise NotFound("Espace de travail introuvable.")
    if payload.name:
        row.name = payload.name.strip()
    await session.commit()
    membership = (
        await session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == tenant.user_id
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = TenantMembership(tenant_id=tenant_id, user_id=tenant.user_id, role=tenant.role)
    return tenant_dict(row, membership)


@router.get("/tenants/{tenant_id}/members")
async def list_members(
    tenant_id: uuid.UUID, tenant: TenantDep, session: SessionDep
) -> list[dict[str, Any]]:
    if tenant.id != tenant_id:
        raise NotFound("Espace de travail introuvable.")
    rows = (
        await session.execute(
            text(
                "select m.id, m.user_id, m.role, m.created_at, p.display_name "
                "from tenant_memberships m left join profiles p on p.id = m.user_id "
                "where m.tenant_id = :t order by m.created_at asc"
            ),
            {"t": str(tenant_id)},
        )
    ).all()
    return [
        {
            "id": str(r[0]),
            "user_id": str(r[1]),
            "role": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "display_name": r[4],
            "is_you": str(r[1]) == str(tenant.user_id),
        }
        for r in rows
    ]


@router.post("/tenants/{tenant_id}/members", status_code=201)
async def add_member(
    tenant_id: uuid.UUID, payload: MemberInvite, tenant: TenantDep, session: SessionDep
) -> dict[str, Any]:
    """Ajoute un utilisateur déjà inscrit, par adresse e-mail.

    Pas d'envoi d'e-mail à ce stade : l'invitation n'existe que si le profil
    correspondant existe déjà côté Supabase.
    """
    if tenant.id != tenant_id or not tenant.can_manage:
        raise NotFound("Espace de travail introuvable.")
    if payload.role not in ROLES or payload.role == "owner":
        raise ValidationFailed("Rôle invité invalide.", {"allowed": ["admin", "member", "viewer"]})

    row = (
        await session.execute(
            text(
                "select p.id from profiles p join auth.users u on u.id = p.id "
                "where lower(u.email) = lower(:email) limit 1"
            ),
            {"email": payload.email.strip()},
        )
    ).first()
    if row is None:
        raise NotFound("Aucun compte Kwes avec cette adresse.")

    exists = (
        await session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == row[0]
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return {"user_id": str(row[0]), "role": exists.role, "already_member": True}

    membership = TenantMembership(tenant_id=tenant_id, user_id=row[0], role=payload.role)
    session.add(membership)
    await session.commit()
    return {"user_id": str(row[0]), "role": membership.role, "already_member": False}


@router.delete("/tenants/{tenant_id}/members/{user_id}", status_code=204)
async def remove_member(
    tenant_id: uuid.UUID, user_id: uuid.UUID, tenant: TenantDep, session: SessionDep
) -> Response:
    if tenant.id != tenant_id or not tenant.can_manage:
        raise NotFound("Espace de travail introuvable.")
    row = (
        await session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Membre introuvable.")
    if row.role == "owner":
        raise ValidationFailed("Le propriétaire ne peut pas être retiré.")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


__all__ = ["router", "WRITE_ROLES", "TenantContext"]

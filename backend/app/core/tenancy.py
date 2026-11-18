"""Tenancy : résolution de l'espace de travail actif.

Règles :

* un utilisateur possède toujours un espace personnel, créé à la première
  requête authentifiée (idempotent : l'identifiant du tenant est celui du
  profil, deux exécutions concurrentes ne créent rien de plus) ;
* un tenant actif peut être demandé par l'en-tête `X-Tenant-Id`, mais il n'est
  accepté que si l'utilisateur en est réellement membre — jamais de confiance
  au navigateur ;
* sans en-tête, l'espace personnel (ou la première appartenance) est retenu.

L'isolation réelle est aussi appliquée en base par les politiques RLS
(migration 0013) : le rôle applicatif ne voit que les lignes de ses tenants.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.core.security import CurrentUser, get_current_user
from app.db.base import get_session
from app.db.models import Profile, Tenant, TenantMembership, TenantSettings

logger = logging.getLogger("kwes.tenancy")

PERSONAL_SLUG_PREFIX = "perso-"

#: Tenant actif de la requête en cours. Rempli par la dépendance `get_tenant`,
#: consommé par le hook d'insertion ci-dessous : aucune route ne peut écrire une
#: ligne sans que son `tenant_id` soit estampillé par le contexte authentifié.
_CURRENT_TENANT: ContextVar[uuid.UUID | None] = ContextVar("kwes_tenant", default=None)


def set_current_tenant(tenant_id: uuid.UUID | None) -> None:
    _CURRENT_TENANT.set(tenant_id)


def current_tenant() -> uuid.UUID | None:
    return _CURRENT_TENANT.get()


@event.listens_for(Session, "before_flush")
def _stamp_tenant_on_new_rows(session: Session, _context, _instances) -> None:  # pragma: no cover
    """Estampille `tenant_id` sur toute ligne créée pendant la requête.

    Filet de sécurité : même un chemin de code oublié (outil, worker, script)
    hérite du tenant actif au lieu d'écrire une ligne orpheline.
    """
    tenant_id = _CURRENT_TENANT.get()
    if tenant_id is None:
        return
    for obj in session.new:
        if not hasattr(type(obj), "tenant_id"):
            continue
        if getattr(obj, "tenant_id", None) is None:
            obj.tenant_id = tenant_id

#: Rôles autorisés à écrire (le rôle `viewer` est en lecture seule).
WRITE_ROLES = frozenset({"owner", "admin", "member"})


@dataclass(frozen=True)
class TenantContext:
    id: uuid.UUID
    name: str
    role: str
    user_id: uuid.UUID | None = None
    slug: str | None = None
    is_personal: bool = False

    @property
    def can_write(self) -> bool:
        return self.role in WRITE_ROLES

    @property
    def can_manage(self) -> bool:
        return self.role in {"owner", "admin"}


def _personal_name(user: CurrentUser) -> str:
    if user.display_name:
        return user.display_name.strip()[:160] or "Mon espace"
    return "Mon espace"


async def ensure_personal_tenant(session: AsyncSession, user: CurrentUser) -> None:
    """Crée l'espace personnel et son appartenance si nécessaire.

    Le tenant porte l'identifiant du profil : la clé primaire rend l'opération
    naturellement idempotente, même sous concurrence. On passe par l'ORM (et non
    par du SQL brut) pour que les types UUID soient convertis de la même façon
    que le reste de l'application — un UUID écrit en texte avec tirets ne
    correspond pas à celui écrit par le mapping `Uuid` sous SQLite.
    """
    existing = await session.get(Tenant, user.id)
    if existing is not None:
        return

    try:
        if await session.get(Profile, user.id) is None:
            session.add(Profile(id=user.id, display_name=user.display_name or None, locale="fr"))
        session.add(
            Tenant(
                id=user.id,
                name=_personal_name(user),
                slug=f"{PERSONAL_SLUG_PREFIX}{str(user.id)[:8]}",
                plan="free",
            )
        )
        session.add(TenantMembership(tenant_id=user.id, user_id=user.id, role="owner"))
        session.add(TenantSettings(tenant_id=user.id))
        await session.commit()
    except IntegrityError as exc:
        # Deux requêtes concurrentes ont créé l'espace en même temps : l'état
        # final est identique, on recharge simplement.
        logger.debug("tenancy.bootstrap concurrent: %s", exc)
        await session.rollback()


async def _membership(session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID):
    return (
        await session.execute(
            select(TenantMembership).where(
                TenantMembership.user_id == user_id,
                TenantMembership.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()


async def _first_membership(session: AsyncSession, user_id: uuid.UUID):
    return (
        await session.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user_id)
            .order_by(TenantMembership.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def resolve_tenant(
    request: Request, user: CurrentUser, session: AsyncSession
) -> TenantContext:
    requested = (request.headers.get("x-tenant-id") or "").strip()

    if requested:
        try:
            tenant_id = uuid.UUID(requested)
        except ValueError as exc:
            raise NotFound("Espace de travail inconnu.") from exc
        membership = await _membership(session, user.id, tenant_id)
        if membership is None:
            # 404 et non 403 : on ne révèle pas l'existence d'un tenant étranger.
            raise NotFound("Espace de travail introuvable.")
    else:
        membership = await _first_membership(session, user.id)
        if membership is None:
            await ensure_personal_tenant(session, user)
            membership = await _membership(session, user.id, user.id)
            if membership is None:
                raise Forbidden("Aucun espace de travail disponible.")
        tenant_id = membership.tenant_id

    tenant_row = await session.get(Tenant, tenant_id)
    if tenant_row is None:
        raise NotFound("Espace de travail introuvable.")

    return TenantContext(
        id=tenant_id,
        name=tenant_row.name,
        slug=tenant_row.slug,
        role=membership.role,
        user_id=user.id,
        is_personal=tenant_id == user.id,
    )


async def get_tenant(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TenantContext:
    tenant = await resolve_tenant(request, user, session)
    set_current_tenant(tenant.id)
    return tenant


async def tenant_settings(session: AsyncSession, tenant_id: uuid.UUID) -> TenantSettings:
    settings = await session.get(TenantSettings, tenant_id)
    if settings is None:
        settings = TenantSettings(tenant_id=tenant_id)
        session.add(settings)
        await session.flush()
    return settings


__all__ = [
    "TenantContext",
    "ensure_personal_tenant",
    "resolve_tenant",
    "get_tenant",
    "tenant_settings",
    "WRITE_ROLES",
]

"""Contexte RLS côté application.

Quand `KWES_RLS_ENABLED=true`, l'application se connecte avec le rôle
`kwes_app` (ni superuser ni `BYPASSRLS`) et déclare, pour chaque transaction,
l'identité de l'utilisateur authentifié. PostgreSQL applique alors réellement
les politiques de la migration 0013 : une requête qui oublierait un filtre
`tenant_id` ne renvoie rien au lieu de tout renvoyer.

`set local` limite l'effet à la transaction courante : la connexion rendue au
pool retrouve son rôle de connexion, aucun risque de fuite entre requêtes.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


def rls_applicable(settings: Settings, session: AsyncSession) -> bool:
    """RLS n'a de sens que sur PostgreSQL : SQLite (tests) n'a pas de rôles."""
    if not settings.db_rls_enabled:
        return False
    return session.bind is not None and session.bind.dialect.name == "postgresql"


async def apply_rls_context(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Déclare l'utilisateur courant pour les politiques RLS de la transaction."""
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    await session.execute(
        text("select set_config('request.jwt.claims', :claims, true)"), {"claims": claims}
    )
    await session.execute(text("set local role authenticated"))


__all__ = ["apply_rls_context", "rls_applicable"]

"""Contexte RLS côté application.

Quand `KWES_RLS_ENABLED=true`, l'application se connecte avec le rôle
`kwes_app` (ni superuser ni `BYPASSRLS`) et déclare, pour chaque requête,
l'identité de l'utilisateur authentifié. PostgreSQL applique alors réellement
les politiques de la migration 0013 : une requête qui oublierait un filtre
`tenant_id` ne renvoie rien au lieu de tout renvoyer.

Le contexte est posé **au niveau de la connexion**, via un écouteur de pool
(`checkout`). C'est indispensable : `commit()` rend la connexion au pool, et
l'instruction suivante peut en recevoir une autre, sans identité — l'insertion
d'audit ou de session vocale échouait alors de façon intermittente.
"""

from __future__ import annotations

import json
import uuid
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings

# Utilisateur courant de la tâche HTTP en cours (None = pas d'identité).
_CURRENT_USER: ContextVar[uuid.UUID | None] = ContextVar("kwes_rls_user", default=None)

_EMPTY_CLAIMS = ""


def rls_applicable(settings: Settings, session: AsyncSession) -> bool:
    """RLS n'a de sens que sur PostgreSQL : SQLite (tests) n'a pas de rôles."""
    # Le worker (DB_RLS_BYPASS) se connecte avec le rôle propriétaire : il n'a pas
    # le droit d'endosser `authenticated`, et n'en a pas besoin.
    if not settings.db_rls_enabled or settings.db_rls_bypass:
        return False
    return session.bind is not None and session.bind.dialect.name == "postgresql"


def install_rls_listener(engine) -> None:
    """Pose rôle et claims à chaque connexion empruntée au pool.

    Sans cela, une connexion rendue au pool après un `commit()` revient sans
    identité : les politiques refusent alors les écritures (audit, sessions
    vocales) de manière apparemment aléatoire.
    """
    sync_engine = engine.sync_engine
    if getattr(sync_engine, "_kwes_rls_listener", False):
        return
    sync_engine._kwes_rls_listener = True  # type: ignore[attr-defined]

    @event.listens_for(sync_engine, "checkout")
    def _on_checkout(dbapi_connection, connection_record, connection_proxy):  # noqa: ANN001
        user_id = _CURRENT_USER.get()
        cursor = dbapi_connection.cursor()
        try:
            if user_id is None:
                cursor.execute("reset role")
                cursor.execute("select set_config('request.jwt.claims', %s, false)", (_EMPTY_CLAIMS,))
            else:
                claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
                cursor.execute("select set_config('request.jwt.claims', %s, false)", (claims,))
                cursor.execute("set role authenticated")
        finally:
            cursor.close()


def set_rls_user(user_id: uuid.UUID | None) -> None:
    """Mémorise l'utilisateur courant pour les connexions à venir."""
    _CURRENT_USER.set(user_id)


async def apply_rls_context(session: AsyncSession, user_id: uuid.UUID | None) -> None:
    """Déclare l'utilisateur courant et l'applique à la connexion en cours."""
    set_rls_user(user_id)
    if user_id is None:
        await session.execute(text("reset role"))
        return
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    await session.execute(
        text("select set_config('request.jwt.claims', :claims, false)"), {"claims": claims}
    )
    await session.execute(text("set role authenticated"))


__all__ = ["apply_rls_context", "install_rls_listener", "rls_applicable", "set_rls_user"]

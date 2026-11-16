"""Routes de développement — JAMAIS actives en production.

`POST /api/v1/dev/token` crée (si besoin) l'utilisateur d'authentification local
et le profil correspondant, puis renvoie un JWT HS256 signé avec DEV_JWT_SECRET.

Double verrou :
  1. `APP_ENV` doit valoir `dev` (ou `test`) ;
  2. `DEV_ENDPOINTS=true` doit être explicitement présent dans l'environnement.

En production Supabase, les utilisateurs sont créés par Supabase Auth : ces
routes ne doivent pas exister.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from jose import jwt
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Forbidden
from app.db.base import get_session
from app.db.models import Profile

router = APIRouter(tags=["dev"])


class DevTokenRequest(BaseModel):
    email: str = Field(default="dev@kwes.local", pattern=r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
    display_name: str | None = Field(default="Utilisateur dev", max_length=120)


class DevTokenResponse(BaseModel):
    token: str
    user_id: str
    email: str
    expires_in: int
    mode: str = "dev"


async def _ensure_auth_user(session: AsyncSession, user_id: uuid.UUID, email: str) -> uuid.UUID:
    """Retourne l'id de l'utilisateur d'authentification pour cet e-mail.

    Réutilise la ligne existante (même e-mail = même identité, comme un vrai
    login), sinon en crée une dans `auth.users` quand la table existe.
    Hors PostgreSQL/Supabase local, l'id fourni est conservé.
    """
    try:
        row = (
            await session.execute(
                text("select id from auth.users where email = :email"), {"email": email}
            )
        ).first()
    except Exception:  # noqa: BLE001 — table auth absente (SQLite, autre moteur)
        await session.rollback()
        return user_id

    if row is not None:
        return uuid.UUID(str(row[0]))

    try:
        await session.execute(
            text("insert into auth.users (id, email) values (:id, :email)"),
            {"id": str(user_id), "email": email},
        )
        await session.flush()
    except Exception:  # noqa: BLE001 — schéma auth différent (Supabase managé)
        await session.rollback()
    return user_id


@router.post("/dev/token", response_model=DevTokenResponse)
async def create_dev_token(
    payload: DevTokenRequest,
    session: AsyncSession = Depends(get_session),
) -> Any:
    settings = get_settings()
    if settings.app_env not in ("dev", "test") or not settings.dev_endpoints:
        raise Forbidden("Route de développement désactivée.")

    user_id = await _ensure_auth_user(session, uuid.uuid4(), str(payload.email))

    if await session.get(Profile, user_id) is None:
        session.add(
            Profile(
                id=user_id,
                display_name=payload.display_name or "Utilisateur dev",
                locale="fr",
            )
        )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if await session.get(Profile, user_id) is None:
            raise

    exp = datetime.now(timezone.utc) + timedelta(hours=12)
    token = jwt.encode(
        {"sub": str(user_id), "email": str(payload.email), "exp": exp, "role": "authenticated"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return DevTokenResponse(
        token=token,
        user_id=str(user_id),
        email=str(payload.email),
        expires_in=12 * 3600,
    )
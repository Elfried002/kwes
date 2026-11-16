"""Authentification JWT HS256 et résolution de l'utilisateur courant.

Dev  : jeton signé avec DEV_JWT_SECRET (défaut `dev-secret-change-me`).
Prod : jeton Supabase vérifié avec SUPABASE_JWT_SECRET.
Le profil applicatif est créé automatiquement s'il n'existe pas.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Unauthenticated
from app.db.base import get_session
from app.db.models import Profile

logger = logging.getLogger("kwes.auth")

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    display_name: str | None
    locale: str
    token_exp: datetime | None = None

    @property
    def actor_id(self) -> str:
        return str(self.id)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    secret = settings.jwt_secret
    if not secret:
        # Échec fermé : aucune vérification possible sans secret.
        logger.error("JWT secret manquant pour app_env=%s", settings.app_env)
        raise Unauthenticated("Configuration d'authentification invalide.")

    options = {"verify_aud": bool(settings.jwt_audience), "verify_exp": True}
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience or None,
            options=options,
        )
    except ExpiredSignatureError as exc:
        raise Unauthenticated("Session expirée.") from exc
    except JWTError as exc:
        raise Unauthenticated("Jeton invalide.") from exc

    if "exp" not in payload:
        raise Unauthenticated("Jeton sans expiration.")
    if "sub" not in payload:
        raise Unauthenticated("Jeton sans sujet.")
    try:
        uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise Unauthenticated("Sujet de jeton invalide.") from exc
    return payload


async def resolve_user(
    payload: dict[str, Any], session: AsyncSession, settings: Settings
) -> CurrentUser:
    user_id = uuid.UUID(str(payload["sub"]))
    email = str(payload.get("email") or f"{user_id}@users.kwes.local")
    exp_ts = payload.get("exp")
    token_exp = (
        datetime.fromtimestamp(float(exp_ts), tz=timezone.utc) if exp_ts is not None else None
    )

    profile = await session.get(Profile, user_id)
    if profile is None:
        profile = Profile(
            id=user_id,
            display_name=str(payload.get("name") or payload.get("display_name") or "") or None,
            locale=str(payload.get("locale") or "fr"),
        )
        session.add(profile)
        try:
            await session.flush()
        except IntegrityError:
            # Course entre deux requêtes concurrentes : le profil existe déjà.
            await session.rollback()
            profile = await session.get(Profile, user_id)
            if profile is None:
                raise Unauthenticated("Profil introuvable.") from None

    return CurrentUser(
        id=user_id,
        email=email,
        display_name=profile.display_name,
        locale=profile.locale,
        token_exp=token_exp,
    )


async def authenticate_token(
    token: str, session: AsyncSession, settings: Settings
) -> CurrentUser:
    """Point d'entrée partagé HTTP / WebSocket."""
    payload = decode_token(token, settings)
    return await resolve_user(payload, session, settings)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if credentials is None or not credentials.credentials:
        raise Unauthenticated("En-tête Authorization manquant.")
    if credentials.scheme.lower() != "bearer":
        raise Unauthenticated("Schéma d'authentification non supporté.")
    return await authenticate_token(credentials.credentials, session, settings)


def create_dev_token(
    user_id: uuid.UUID | str,
    email: str = "demo@kwes.local",
    settings: Settings | None = None,
    ttl_minutes: int = 60,
    secret: str | None = None,
) -> str:
    """Utilitaire dev/démo et tests. Jamais utilisé par les routes de production."""
    settings = settings or Settings(app_env="dev")
    key = secret or settings.jwt_secret
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "aud": "authenticated",
        "role": "authenticated",
    }
    return jwt.encode(payload, key, algorithm="HS256")

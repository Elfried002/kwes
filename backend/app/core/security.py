"""Authentification JWT et résolution de l'utilisateur courant.

Règles par environnement (P0.1) :

* **production** : seul ES256 est accepté, clé résolue par JWKS Supabase, avec
  vérification de la signature, de l'expiration, de l'émetteur (`<supabase>/auth/v1`),
  de l'audience (`authenticated`) et du sujet. Aucun jeton symétrique n'est
  accepté : un HS256 signé avec un secret local est refusé.
* **dev / test** : HS256 avec `DEV_JWT_SECRET`, uniquement pour les outils locaux
  et la suite de tests.

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
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Unauthenticated
from app.db.base import get_session
from app.db.rls import apply_rls_context, rls_applicable
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


def _jwks_cache(settings: Settings) -> dict[str, Any]:
    """Récupère et met en cache (10 min) le JWKS Supabase (clés ES256)."""
    import json
    import time
    import urllib.request

    global _JWKS
    now = time.time()
    cached = _JWKS.get("data")
    if cached and now - _JWKS.get("at", 0) < 600:
        return cached
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=8) as r:  # noqa: S310 — URL de configuration
        data = json.loads(r.read().decode("utf-8"))
    _JWKS = {"data": data, "at": now}
    return data


_JWKS: dict[str, Any] = {}


PRODUCTION_ALGORITHMS = frozenset({"ES256"})
SUPABASE_AUDIENCE = "authenticated"


def _decode_supabase_es256(token: str, settings: Settings) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    keys = _jwks_cache(settings).get("keys", [])
    jwk = next((k for k in keys if k.get("kid") == kid), None)
    if jwk is None:
        _JWKS.clear()
        keys = _jwks_cache(settings).get("keys", [])
        jwk = next((k for k in keys if k.get("kid") == kid), None)
    if jwk is None:
        raise Unauthenticated("Clé de signature inconnue.")
    payload = jwt.decode(
        token,
        jwk,
        algorithms=["ES256"],
        audience=SUPABASE_AUDIENCE,
        issuer=settings.jwt_issuer or None,
        options={
            "verify_aud": True,
            "verify_exp": True,
            "verify_iss": bool(settings.jwt_issuer),
            "require_exp": True,
            "require_sub": True,
            "require_aud": True,
        },
    )
    return payload


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Vérifie un JWT selon l'environnement, sans repli permissif.

    Production : ES256 uniquement, JWKS Supabase, émetteur et audience vérifiés.
    Dev/test   : HS256 uniquement, avec le secret local.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise Unauthenticated("Jeton invalide.") from exc

    alg = str(header.get("alg") or "")

    if settings.is_production:
        if alg not in PRODUCTION_ALGORITHMS:
            logger.warning("auth.refus raison=algorithme_non_autorise alg=%s", alg or "absent")
            raise Unauthenticated("Algorithme de signature non autorisé.")
        if not settings.supabase_url or not settings.jwt_issuer:
            logger.error("auth.refus raison=configuration_incomplete (SUPABASE_URL absent)")
            raise Unauthenticated("Configuration d'authentification incomplète.")
        try:
            payload = _decode_supabase_es256(token, settings)
        except ExpiredSignatureError as exc:
            logger.warning("auth.refus raison=jeton_expire")
            raise Unauthenticated("Session expirée.") from exc
        except JWTError as exc:
            logger.warning("auth.refus raison=signature_ou_claims_invalides")
            raise Unauthenticated("Jeton invalide.") from exc
    else:
        # Aucun repli : l'algorithme doit être exactement celui du mode courant.
        if alg != settings.jwt_algorithm:
            logger.warning("auth.refus raison=algorithme_inattendu alg=%s", alg or "absent")
            raise Unauthenticated("Algorithme de signature non autorisé.")
        secret = settings.jwt_secret
        if not secret:
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
        # Sur Supabase, la ligne auth.users existe déjà (créée à l'inscription).
        # En local (PostgreSQL nu), il faut la créer pour satisfaire la clé
        # étrangère profiles.id -> auth.users.id.
        try:
            await session.execute(
                text(
                    "insert into auth.users (id, email) values (:id, :email) "
                    "on conflict (id) do nothing"
                ),
                {"id": str(user_id), "email": email},
            )
            # Commit immédiat : la ligne d'authentification doit exister avant
            # l'insertion du profil, sinon la clé étrangère fait échouer la
            # transaction entière et la première connexion renvoie 401.
            await session.commit()
        except Exception:  # noqa: BLE001 — schéma auth absent (SQLite) ou droits insuffisants
            await session.rollback()

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
    """Point d'entrée partagé HTTP / WebSocket.

    La RLS est déclarée *avant* la création éventuelle du profil : la politique
    `profiles_insert` exige `id = auth.uid()`, donc l'identité doit déjà être
    posée quand la première requête d'un nouvel utilisateur arrive.
    """
    payload = decode_token(token, settings)
    if rls_applicable(settings, session):
        await apply_rls_context(session, uuid.UUID(str(payload["sub"])))
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
    if settings.is_production:
        # Ceinture et bretelles : même appelé par erreur, aucun jeton de
        # développement ne peut être forgé lorsque l'application est en prod.
        raise RuntimeError("create_dev_token est interdit en production.")
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

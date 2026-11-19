"""Connecteurs : catalogue, connexion OAuth, test, révocation.

Règles appliquées ici :
  * aucune clé de fournisseur n'est inventée : sans identifiants serveur, la
    connexion est refusée avec un statut explicite (`needs_configuration`) ;
  * le `state` OAuth est à usage unique, lié au tenant et à l'utilisateur ;
  * les jetons sont chiffrés avant stockage et ne sortent jamais de l'API.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SessionDep, SettingsDep, TenantDep, UserDep
from app.connectors import oauth as broker
from app.connectors.catalog import list_catalog
from app.connectors.vault import decrypt, encrypt, reference
from app.core.errors import NotFound, ValidationFailed
from app.db.models import ConnectorCatalog, ConnectorSecret, OAuthState, TenantConnection

logger = logging.getLogger("kwes.connectors.api")

router = APIRouter(tags=["connectors"])


def _callback_url(settings: Any) -> str:
    return f"{settings.public_api_url.rstrip('/')}/api/v1/connectors/callback"


@router.get("/connectors")
async def list_connectors(
    session: SessionDep,
    user: UserDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    catalogue = await list_catalog(session)
    connexions = (
        await session.execute(
            select(TenantConnection).where(
                TenantConnection.tenant_id == tenant.id,
                TenantConnection.owner_user_id == user.id,
            )
        )
    ).scalars().all()
    par_provider = {c.provider_id: c for c in connexions}
    items = []
    for entree in catalogue:
        connexion = par_provider.get(entree["provider_id"])
        items.append(
            {
                **entree,
                "connection": (
                    {
                        "id": str(connexion.id),
                        "status": connexion.status,
                        "account": connexion.account_label,
                        "scopes": connexion.scopes,
                        "last_checked_at": connexion.last_checked_at.isoformat()
                        if connexion.last_checked_at
                        else None,
                        "last_error": connexion.last_error,
                    }
                    if connexion
                    else None
                ),
            }
        )
    return {"items": items}


class ConnectOut(BaseModel):
    authorize_url: str
    state: str


@router.post("/connectors/{provider_id}/connect", response_model=ConnectOut)
async def connect_provider(
    provider_id: str,
    session: SessionDep,
    settings: SettingsDep,
    user: UserDep,
    tenant: TenantDep,
) -> ConnectOut:
    provider = await session.get(ConnectorCatalog, provider_id)
    if provider is None:
        raise NotFound("Connecteur inconnu.")
    if provider.auth_mode not in {"oauth2", "oauth2_pkce"}:
        raise ValidationFailed(
            "Ce connecteur ne passe pas par OAuth : utilisez le formulaire de clé d'accès."
        )
    if broker.client_credentials(provider_id) is None:
        raise ValidationFailed(
            "Identifiants serveur absents pour ce fournisseur : la connexion ne peut pas "
            "démarrer. Les identifiants doivent être configurés côté serveur."
        )

    state = broker.new_state()
    verifier, challenge = broker.pkce_pair()
    session.add(
        OAuthState(
            state=state,
            tenant_id=tenant.id,
            user_id=user.id,
            provider_id=provider_id,
            code_verifier=verifier,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
    )
    await session.commit()

    scopes = [s["scope"] for s in (provider.scopes or [])]
    url = broker.authorize_url(
        provider_id,
        redirect_uri=_callback_url(settings),
        state=state,
        challenge=challenge,
        scopes=scopes,
    )
    return ConnectOut(authorize_url=url, state=state)


@router.get("/connectors/callback")
async def oauth_callback(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Retour du fournisseur : valide le state, échange le code, stocke chiffré."""
    cible = f"{settings.frontend_url.rstrip('/')}/#/reglages/connecteurs"
    if not state:
        return RedirectResponse(f"{cible}?erreur=state_manquant", status_code=303)

    etat = await session.get(OAuthState, state)
    if etat is None or etat.consumed:
        return RedirectResponse(f"{cible}?erreur=state_invalide", status_code=303)
    if etat.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return RedirectResponse(f"{cible}?erreur=state_expire", status_code=303)
    if error:
        etat.consumed = True
        await session.commit()
        return RedirectResponse(f"{cible}?erreur=refus_fournisseur", status_code=303)
    if not code:
        return RedirectResponse(f"{cible}?erreur=code_manquant", status_code=303)

    # Consommation immédiate : un rejeu du même state est refusé même si
    # l'échange échoue ensuite (anti-replay).
    etat.consumed = True
    await session.commit()

    try:
        jetons = await broker.exchange_code(
            etat.provider_id,
            code=code,
            verifier=etat.code_verifier or "",
            redirect_uri=_callback_url(settings),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Échange OAuth refusé pour %s : %s", etat.provider_id, exc)
        return RedirectResponse(f"{cible}?erreur=echange_refuse", status_code=303)

    ref = reference(etat.tenant_id, etat.provider_id, etat.user_id)
    secret = {
        "access_token": jetons.get("access_token"),
        "refresh_token": jetons.get("refresh_token"),
        "expires_in": jetons.get("expires_in"),
        "scope": jetons.get("scope"),
    }
    chiffre = encrypt(settings, secret)
    existant = await session.get(ConnectorSecret, (etat.tenant_id, ref))
    if existant is None:
        session.add(
            ConnectorSecret(
                tenant_id=etat.tenant_id,
                ref=ref,
                provider_id=etat.provider_id,
                ciphertext=chiffre,
            )
        )
    else:
        existant.ciphertext = chiffre
        existant.updated_at = datetime.now(timezone.utc)

    connexion = (
        await session.execute(
            select(TenantConnection).where(
                TenantConnection.tenant_id == etat.tenant_id,
                TenantConnection.provider_id == etat.provider_id,
                TenantConnection.owner_user_id == etat.user_id,
            )
        )
    ).scalar_one_or_none()
    expire = jetons.get("expires_in")
    if connexion is None:
        connexion = TenantConnection(
            tenant_id=etat.tenant_id,
            owner_user_id=etat.user_id,
            provider_id=etat.provider_id,
        )
        session.add(connexion)
    connexion.status = "active"
    connexion.secret_ref = ref
    connexion.scopes = str(jetons.get("scope") or "").split() or []
    connexion.expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expire)) if expire else None
    )
    connexion.last_checked_at = datetime.now(timezone.utc)
    connexion.last_error = None
    await session.commit()

    return RedirectResponse(f"{cible}?connecte={etat.provider_id}", status_code=303)


class TokenIn(BaseModel):
    """Connexion manuelle (bot Telegram, jeton WhatsApp Business)."""

    token: str = Field(min_length=8, max_length=4000)
    account_label: str | None = Field(default=None, max_length=160)


@router.post("/connectors/{provider_id}/token", status_code=201)
async def connect_with_token(
    provider_id: str,
    payload: TokenIn,
    session: SessionDep,
    settings: SettingsDep,
    user: UserDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    provider = await session.get(ConnectorCatalog, provider_id)
    if provider is None:
        raise NotFound("Connecteur inconnu.")
    if provider.auth_mode not in {"bot_token", "api_key"}:
        raise ValidationFailed("Ce connecteur attend une autorisation OAuth, pas une clé.")

    ref = reference(tenant.id, provider_id, user.id)
    chiffre = encrypt(settings, {"token": payload.token})
    existant = await session.get(ConnectorSecret, (tenant.id, ref))
    if existant is None:
        session.add(
            ConnectorSecret(
                tenant_id=tenant.id, ref=ref, provider_id=provider_id, ciphertext=chiffre
            )
        )
    else:
        existant.ciphertext = chiffre
        existant.updated_at = datetime.now(timezone.utc)

    connexion = (
        await session.execute(
            select(TenantConnection).where(
                TenantConnection.tenant_id == tenant.id,
                TenantConnection.provider_id == provider_id,
                TenantConnection.owner_user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if connexion is None:
        connexion = TenantConnection(
            tenant_id=tenant.id, owner_user_id=user.id, provider_id=provider_id
        )
        session.add(connexion)
    connexion.status = "active"
    connexion.secret_ref = ref
    connexion.account_label = payload.account_label
    connexion.last_checked_at = datetime.now(timezone.utc)
    connexion.last_error = None
    await session.commit()
    return {"provider_id": provider_id, "status": "active", "stored": True}


@router.post("/connectors/{provider_id}/test")
async def test_connection(
    provider_id: str,
    session: SessionDep,
    settings: SettingsDep,
    user: UserDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """Vérifie qu'un secret existe et qu'il est déchiffrable (pas d'appel externe)."""
    ref = reference(tenant.id, provider_id, user.id)
    existant = await session.get(ConnectorSecret, (tenant.id, ref))
    if existant is None:
        raise NotFound("Aucune connexion enregistrée pour ce fournisseur.")
    try:
        secret = decrypt(settings, existant.ciphertext)
    except Exception:  # noqa: BLE001
        return {"provider_id": provider_id, "ok": False, "reason": "secret_illisible"}
    present = bool(secret.get("access_token") or secret.get("token"))
    return {
        "provider_id": provider_id,
        "ok": present,
        "reason": "secret_present" if present else "secret_incomplet",
    }


@router.delete("/connectors/{provider_id}")
async def disconnect(
    provider_id: str,
    session: SessionDep,
    user: UserDep,
    tenant: TenantDep,
    response: Response,
) -> dict[str, Any]:
    """Déconnecte et supprime le secret. Aucun jeton résiduel ne doit rester."""
    connexion = (
        await session.execute(
            select(TenantConnection).where(
                TenantConnection.tenant_id == tenant.id,
                TenantConnection.provider_id == provider_id,
                TenantConnection.owner_user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    ref = reference(tenant.id, provider_id, user.id)
    secret = await session.get(ConnectorSecret, (tenant.id, ref))
    if secret is not None:
        await session.delete(secret)
    if connexion is not None:
        connexion.status = "revoked"
        connexion.secret_ref = None
    await session.commit()
    return {"provider_id": provider_id, "status": "revoked", "deleted": secret is not None}

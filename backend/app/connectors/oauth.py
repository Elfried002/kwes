"""Broker OAuth : autorisation, échange de code, rafraîchissement.

Aucun jeton n'est transmis au navigateur : le code d'autorisation revient au
serveur, qui échange, chiffre et stocke. Le `state` est à usage unique et lié au
tenant et à l'utilisateur qui a lancé la connexion.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class ProviderOAuth:
    authorize_url: str
    token_url: str
    extra_authorize: dict[str, str]


PROVIDERS: dict[str, ProviderOAuth] = {
    "google": ProviderOAuth(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        extra_authorize={"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"},
    ),
    "microsoft": ProviderOAuth(
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        extra_authorize={"response_mode": "query"},
    ),
}


def new_state() -> str:
    return secrets.token_urlsafe(32)


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge S256)."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def client_credentials(provider_id: str) -> tuple[str, str] | None:
    prefix = provider_id.upper()
    client_id = os.getenv(f"{prefix}_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv(f"{prefix}_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def authorize_url(
    provider_id: str,
    *,
    redirect_uri: str,
    state: str,
    challenge: str,
    scopes: list[str],
) -> str:
    spec = PROVIDERS[provider_id]
    params = {
        "client_id": client_credentials(provider_id)[0],  # type: ignore[index]
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **spec.extra_authorize,
    }
    return f"{spec.authorize_url}?{urlencode(params)}"


async def exchange_code(
    provider_id: str,
    *,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    spec = PROVIDERS[provider_id]
    credentials = client_credentials(provider_id)
    if credentials is None:
        raise RuntimeError("Identifiants OAuth absents.")
    client_id, client_secret = credentials
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": verifier,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(spec.token_url, data=payload)
    if response.status_code >= 400:
        # Le corps peut contenir des indices (invalid_grant) mais jamais de secret.
        raise RuntimeError(f"Échange OAuth refusé ({response.status_code}).")
    return response.json()

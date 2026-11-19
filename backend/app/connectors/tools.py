"""Outils issus des connecteurs : pont entre une connexion utilisateur et l'agent.

Un outil de connecteur n'existe que si le tenant possède une connexion active :
le runtime ne reçoit jamais un outil sans secret, et un appel sans connexion est
refusé explicitement (`CONNECTOR_NOT_CONNECTED`).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import select

from app.connectors.vault import decrypt, reference
from app.db.models import ConnectorSecret, TenantConnection

logger = logging.getLogger("kwes.connectors.tools")


class ConnectorToolError(RuntimeError):
    def __init__(self, message: str, code: str = "CONNECTOR_FAILED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ConnectorToolSpec:
    name: str
    provider_id: str
    description: str
    parameters: dict[str, Any]


#: Catalogue des outils exposables. Un outil n'est visible que si le fournisseur
#: est connecté ; sinon il n'apparaît pas dans la liste des outils de l'agent.
TOOL_SPECS: dict[str, ConnectorToolSpec] = {
    "gmail.read": ConnectorToolSpec(
        name="gmail.read",
        provider_id="google",
        description="Lire les derniers e-mails du compte connecté (objets, expéditeurs, dates).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": [],
        },
    ),
    "telegram.send": ConnectorToolSpec(
        name="telegram.send",
        provider_id="telegram",
        description="Envoyer un message Telegram via le bot connecté par l'utilisateur.",
        parameters={
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "maxLength": 64},
                "text": {"type": "string", "maxLength": 3000},
            },
            "required": ["chat_id", "text"],
        },
    ),
}


async def active_tools(db: Any, tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """Outils disponibles pour ce tenant : uniquement ceux dont la connexion est active."""
    async with db.session() as session:
        lignes = (
            await session.execute(
                select(TenantConnection.provider_id).where(
                    TenantConnection.tenant_id == tenant_id,
                    TenantConnection.owner_user_id == user_id,
                    TenantConnection.status == "active",
                )
            )
        ).scalars().all()
    connectes = set(lignes)
    return [nom for nom, spec in TOOL_SPECS.items() if spec.provider_id in connectes]


def definitions(tool_names: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for nom in tool_names:
        spec = TOOL_SPECS.get(nom)
        if spec is None:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
        )
    return out


async def _secret(db: Any, settings: Any, tenant_id: uuid.UUID, user_id: uuid.UUID, provider: str) -> dict[str, Any]:
    ref = reference(tenant_id, provider, user_id)
    async with db.session() as session:
        ligne = await session.get(ConnectorSecret, (tenant_id, ref))
    if ligne is None:
        raise ConnectorToolError(
            "Aucune connexion active pour ce fournisseur.", code="CONNECTOR_NOT_CONNECTED"
        )
    try:
        return decrypt(settings, ligne.ciphertext)
    except Exception as exc:  # noqa: BLE001
        raise ConnectorToolError("Secret illisible.", code="CONNECTOR_SECRET_UNREADABLE") from exc


async def _gmail_read(payload: dict[str, Any], ctx: Any) -> dict[str, Any]:
    secret = await _secret(ctx.db, ctx.settings, ctx.tenant_id, ctx.user_id, "google")
    token = secret.get("access_token")
    if not token:
        raise ConnectorToolError("Jeton Google absent.", code="CONNECTOR_NOT_CONNECTED")

    limite = int(payload.get("limit") or 5)
    params = {"maxResults": max(1, min(limite, 10))}
    if payload.get("query"):
        params["q"] = str(payload["query"])[:200]

    async with httpx.AsyncClient(timeout=20.0) as client:
        liste = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if liste.status_code == 401:
            raise ConnectorToolError("Jeton Google expiré.", code="CONNECTOR_TOKEN_EXPIRED")
        if liste.status_code >= 400:
            raise ConnectorToolError(f"Gmail a refusé la lecture ({liste.status_code}).")
        ids = [m["id"] for m in liste.json().get("messages", [])][:limite]

        messages = []
        for identifiant in ids:
            detail = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{identifiant}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                headers={"Authorization": f"Bearer {token}"},
            )
            if detail.status_code >= 400:
                continue
            data = detail.json()
            entetes = {
                h["name"].lower(): h["value"]
                for h in data.get("payload", {}).get("headers", [])
                if "name" in h
            }
            messages.append(
                {
                    "id": identifiant,
                    "subject": entetes.get("subject", "(sans objet)")[:200],
                    "from": entetes.get("from", "")[:160],
                    "date": entetes.get("date", "")[:80],
                    "snippet": data.get("snippet", "")[:200],
                }
            )
    return {"messages": messages, "count": len(messages)}


async def _telegram_send(payload: dict[str, Any], ctx: Any) -> dict[str, Any]:
    secret = await _secret(ctx.db, ctx.settings, ctx.tenant_id, ctx.user_id, "telegram")
    token = secret.get("token")
    if not token:
        raise ConnectorToolError("Jeton Telegram absent.", code="CONNECTOR_NOT_CONNECTED")

    async with httpx.AsyncClient(timeout=20.0) as client:
        reponse = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": payload["chat_id"], "text": str(payload["text"])[:3000]},
        )
    data = reponse.json() if reponse.headers.get("content-type", "").startswith("application/json") else {}
    if reponse.status_code >= 400 or not data.get("ok"):
        raise ConnectorToolError(
            f"Telegram a refusé l'envoi ({data.get('description') or reponse.status_code})."
        )
    resultat = data.get("result") or {}
    return {
        "message_id": resultat.get("message_id"),
        "chat": (resultat.get("chat") or {}).get("id"),
        "sent": True,
    }


HANDLERS: dict[str, Callable[[dict[str, Any], Any], Awaitable[dict[str, Any]]]] = {
    "gmail.read": _gmail_read,
    "telegram.send": _telegram_send,
}


async def call(name: str, payload: dict[str, Any], ctx: Any) -> dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ConnectorToolError(f"Outil de connecteur inconnu : {name}", code="TOOL_NOT_ALLOWED")
    return await handler(payload, ctx)

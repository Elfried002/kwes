"""Connecteurs d'appareil — enregistrement, capacités, commandes, révocation.

Le moteur d'orchestration ne connaît que des **capacités**. Un appareil
(compagnon Android, agent desktop, connecteur cloud) s'enregistre, déclare ce
qu'il sait faire, et reçoit des commandes. Il s'authentifie par un jeton dédié
(X-Device-Token), indépendant de la session utilisateur : un appareil ne donne
jamais accès au compte.

Règles :
- le jeton n'est affiché qu'une fois ; seul son SHA-256 est stocké ;
- un connecteur ne peut pas s'attribuer une capacité non déclarée à l'inscription ;
- aucun résultat n'est accepté sans identifiant de commande ;
- la révocation est immédiate côté serveur, même si l'appareil est hors ligne.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TenantDep, UserDep
from app.core.errors import Forbidden, NotFound, Unauthenticated, ValidationFailed
from app.db.base import get_session
from app.db.models import DeviceCommand, DeviceConnector

router = APIRouter(tags=["devices"])

PLATFORMS = {"android", "ios", "windows", "linux", "macos", "cloud"}


class RegisterRequest(BaseModel):
    connector_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    platform: str = Field(pattern=r"^(android|ios|windows|linux|macos|cloud)$")
    connector_version: str = Field(default="0.1.0", max_length=32)
    capabilities: list[str] = Field(default_factory=list, max_length=64)
    permissions: dict[str, str] = Field(default_factory=dict)


class RegisterResponse(BaseModel):
    id: str
    connector_id: str
    platform: str
    token: str
    capabilities: list[str]
    notice: str = "Conservez ce jeton : il ne sera plus affiché."


class ConnectorOut(BaseModel):
    id: str
    connector_id: str
    platform: str
    connector_version: str
    capabilities: list[str]
    permissions: dict[str, str]
    status: str
    last_seen_at: str | None


class HeartbeatRequest(BaseModel):
    permissions: dict[str, str] = Field(default_factory=dict)
    connector_version: str | None = Field(default=None, max_length=32)


class CommandOut(BaseModel):
    id: str
    capability: str
    payload: dict[str, Any]
    created_at: str


class ResultRequest(BaseModel):
    status: str = Field(pattern=r"^(succeeded|failed)$")
    result: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=64)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


async def device_from_token(
    session: AsyncSession,
    token: str,
) -> DeviceConnector:
    if not token:
        raise Unauthenticated("Jeton de connecteur manquant.")
    row = (
        await session.execute(
            select(DeviceConnector).where(DeviceConnector.token_hash == _hash(token))
        )
    ).scalar_one_or_none()
    if row is None:
        raise Unauthenticated("Jeton de connecteur invalide.")
    if row.status == "revoked":
        raise Forbidden("Connecteur révoqué.")
    return row


async def _connector_from_header(
    x_device_token: Annotated[str | None, Header(alias="X-Device-Token")] = None,
    session: AsyncSession = Depends(get_session),
) -> DeviceConnector:
    return await device_from_token(session, x_device_token or "")


DeviceDep = Annotated[DeviceConnector, Depends(_connector_from_header)]


@router.post("/devices", response_model=RegisterResponse, status_code=201)
async def register_device(
    payload: RegisterRequest, user: UserDep, tenant: TenantDep, session: AsyncSession = Depends(get_session)
) -> Any:
    token = secrets.token_urlsafe(32)
    existing = (
        await session.execute(
            select(DeviceConnector).where(
                DeviceConnector.user_id == user.id,
                DeviceConnector.connector_id == payload.connector_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Ré-enregistrement : le jeton précédent est invalidé (rotation).
        existing.platform = payload.platform
        existing.connector_version = payload.connector_version
        existing.capabilities = payload.capabilities
        existing.permissions = payload.permissions
        existing.status = "active"
        existing.token_hash = _hash(token)
        existing.updated_at = datetime.now(timezone.utc)
        connector = existing
    else:
        connector = DeviceConnector(
            id=uuid.uuid4(),
            user_id=user.id,
            connector_id=payload.connector_id,
            platform=payload.platform,
            connector_version=payload.connector_version,
            capabilities=payload.capabilities,
            permissions=payload.permissions,
            status="active",
            token_hash=_hash(token),
        )
        session.add(connector)

    await session.commit()
    return RegisterResponse(
        id=str(connector.id),
        connector_id=connector.connector_id,
        platform=connector.platform,
        token=token,
        capabilities=list(connector.capabilities or []),
    )


@router.get("/devices", response_model=list[ConnectorOut])
async def list_devices(user: UserDep, tenant: TenantDep, session: AsyncSession = Depends(get_session)) -> Any:
    rows = (
        await session.execute(
            select(DeviceConnector)
            .where(DeviceConnector.user_id == user.id)
            .order_by(DeviceConnector.created_at)
        )
    ).scalars().all()
    return [
        ConnectorOut(
            id=str(r.id),
            connector_id=r.connector_id,
            platform=r.platform,
            connector_version=r.connector_version,
            capabilities=list(r.capabilities or []),
            permissions=dict(r.permissions or {}),
            status=r.status,
            last_seen_at=_iso(r.last_seen_at),
        )
        for r in rows
    ]


@router.delete("/devices/{connector_pk}", status_code=204)
async def revoke_device(
    connector_pk: uuid.UUID, user: UserDep, tenant: TenantDep, session: AsyncSession = Depends(get_session)
) -> None:
    row = await session.get(DeviceConnector, connector_pk)
    if row is None or row.tenant_id != tenant.id:
        raise NotFound("Connecteur introuvable.")
    row.status = "revoked"
    row.token_hash = _hash(secrets.token_urlsafe(8))  # ancien jeton définitivement inutilisable
    row.updated_at = datetime.now(timezone.utc)

    pending = (
        await session.execute(
            select(DeviceCommand).where(
                DeviceCommand.connector_id == row.id, DeviceCommand.status == "queued"
            )
        )
    ).scalars().all()
    for cmd in pending:
        cmd.status = "expired"
        cmd.completed_at = datetime.now(timezone.utc)
    await session.commit()


@router.post("/device/heartbeat")
async def heartbeat(
    payload: HeartbeatRequest,
    device: DeviceDep,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.permissions:
        device.permissions = {**dict(device.permissions or {}), **payload.permissions}
    if payload.connector_version:
        device.connector_version = payload.connector_version
    device.last_seen_at = datetime.now(timezone.utc)
    device.status = "active"
    await session.commit()
    return {
        "ok": True,
        "capabilities": list(device.capabilities or []),
        "pending_commands": int(
            len(
                (
                    await session.execute(
                        select(DeviceCommand).where(
                            DeviceCommand.connector_id == device.id,
                            DeviceCommand.status == "queued",
                        )
                    )
                ).scalars().all()
            )
        ),
    }


@router.get("/device/commands", response_model=list[CommandOut])
async def pending_commands(device: DeviceDep, session: AsyncSession = Depends(get_session)) -> Any:
    rows = (
        await session.execute(
            select(DeviceCommand)
            .where(DeviceCommand.connector_id == device.id, DeviceCommand.status == "queued")
            .order_by(DeviceCommand.created_at)
            .limit(20)
        )
    ).scalars().all()
    out = []
    for cmd in rows:
        cmd.status = "sent"
        out.append(
            CommandOut(
                id=str(cmd.id),
                capability=cmd.capability,
                payload=dict(cmd.payload or {}),
                created_at=_iso(cmd.created_at) or "",
            )
        )
    await session.commit()
    return out


@router.post("/device/commands/{command_id}/result")
async def command_result(
    command_id: uuid.UUID,
    payload: ResultRequest,
    device: DeviceDep,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cmd = await session.get(DeviceCommand, command_id)
    if cmd is None or cmd.connector_id != device.id:
        raise NotFound("Commande introuvable.")
    if cmd.status in ("succeeded", "failed", "expired", "refused"):
        raise ValidationFailed("Commande déjà clôturée.")

    # Une capacité non déclarée à l'enregistrement ne peut pas produire de résultat.
    if cmd.capability not in (device.capabilities or []):
        cmd.status = "refused"
        cmd.error_code = "CAPABILITY_NOT_DECLARED"
        cmd.completed_at = datetime.now(timezone.utc)
        await session.commit()
        raise Forbidden("Capacité non déclarée par ce connecteur.")

    cmd.status = payload.status
    cmd.result = payload.result
    cmd.error_code = payload.error_code
    cmd.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True, "status": cmd.status, "command_id": str(cmd.id)}


async def enqueue_command(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    capability: str,
    payload: dict[str, Any],
    approval_id: uuid.UUID | None = None,
) -> DeviceCommand | None:
    """Utilisé par le Device Router (orchestrateur) : choisit un connecteur actif
    possédant la capacité ET la permission accordée. Retourne None si aucun."""
    rows = (
        await session.execute(
            select(DeviceConnector).where(
                DeviceConnector.user_id == user_id,
                DeviceConnector.status == "active",
            )
        )
    ).scalars().all()

    for connector in rows:
        caps = list(connector.capabilities or [])
        perms = dict(connector.permissions or {})
        if capability not in caps:
            continue
        if perms.get(capability, "granted") != "granted":
            continue
        cmd = DeviceCommand(
            id=uuid.uuid4(),
            connector_id=connector.id,
            user_id=user_id,
            capability=capability,
            payload=payload,
            status="queued",
            approval_id=approval_id,
        )
        session.add(cmd)
        await session.commit()
        return cmd
    return None

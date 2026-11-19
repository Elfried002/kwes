"""Catalogue des connecteurs : chargement, validation, synchronisation.

Un connecteur n'est « disponible » que si son implémentation existe et que les
identifiants serveur sont présents. Sinon il reste visible avec le statut exact
qui empêche la connexion — jamais un bouton qui ne fait rien.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.models import ConnectorCatalog

logger = logging.getLogger("kwes.connectors.catalog")

AUTH_MODES = Literal["oauth2", "oauth2_pkce", "api_key", "bot_token", "none"]


class ScopeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    usage: str
    risk: str


class CapabilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    status: Literal["declared", "implemented", "tested", "staging_verified"] = "declared"


class ConnectorManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(pattern=r"^[a-z0-9_]{3,32}$")
    display_name: str
    category: str
    auth_mode: AUTH_MODES
    docs_url: str | None = None
    env_required: list[str] = Field(default_factory=list)
    scopes: list[ScopeSpec] = Field(default_factory=list)
    capabilities: list[CapabilitySpec] = Field(default_factory=list)
    limits: str | None = None


def load_manifests(root: Path) -> list[ConnectorManifest]:
    """Charge tous les manifestes valides ; un manifeste invalide est ignoré."""
    manifests: list[ConnectorManifest] = []
    if not root.exists():
        return manifests
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            manifests.append(ConnectorManifest.model_validate(data))
        except Exception as exc:  # noqa: BLE001 - un fichier fautif ne bloque pas les autres
            logger.warning("Manifeste connecteur ignoré (%s) : %s", path.name, exc)
    return manifests


def runtime_status(manifest: ConnectorManifest) -> str:
    """Statut réel : disponible seulement si les identifiants serveur existent."""
    if manifest.auth_mode in {"oauth2", "oauth2_pkce"}:
        return (
            "available"
            if all(os.getenv(name) for name in manifest.env_required)
            else "needs_configuration"
        )
    if manifest.auth_mode == "none":
        return "available"
    # bot_token / api_key : le secret est fourni par l'utilisateur, pas par le serveur.
    implemented = any(c.status in {"implemented", "tested"} for c in manifest.capabilities)
    return "available" if implemented else "provider_review"


async def sync_catalog(db: Any, root: Path) -> int:
    """Aligne la table sur les manifestes du dépôt. Retourne le nombre de lignes."""
    manifests = load_manifests(root)
    async with db.session() as session:
        for manifest in manifests:
            row = await session.get(ConnectorCatalog, manifest.provider_id)
            statut = runtime_status(manifest)
            valeurs = dict(
                display_name=manifest.display_name,
                category=manifest.category,
                auth_mode=manifest.auth_mode,
                status=statut,
                capabilities=[c.model_dump() for c in manifest.capabilities],
                scopes=[s.model_dump() for s in manifest.scopes],
                limits=manifest.limits,
                docs_url=manifest.docs_url,
                manifest=manifest.model_dump(),
            )
            if row is None:
                session.add(ConnectorCatalog(provider_id=manifest.provider_id, **valeurs))
            else:
                for key, value in valeurs.items():
                    setattr(row, key, value)
        await session.commit()
    return len(manifests)


async def list_catalog(session: Any) -> list[dict[str, Any]]:
    rows = (await session.execute(select(ConnectorCatalog).order_by(ConnectorCatalog.display_name))).scalars().all()
    return [
        {
            "provider_id": row.provider_id,
            "display_name": row.display_name,
            "category": row.category,
            "auth_mode": row.auth_mode,
            "status": row.status,
            "capabilities": row.capabilities,
            "scopes": row.scopes,
            "limits": row.limits,
            "docs_url": row.docs_url,
        }
        for row in rows
    ]

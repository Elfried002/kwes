"""Journal d'audit (table audit_logs, données expurgées)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import redact
from app.db.models import AuditLog

logger = logging.getLogger("kwes.audit")


async def record_audit(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    decision: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    # Normalisation : les enums internes sont en majuscules (ALLOW, DENY…),
    # la contrainte SQL exige les valeurs minuscules du contrat de données.
    decision_norm = str(decision).strip().lower()
    if decision_norm not in ("allow", "deny", "require_approval", "error"):
        decision_norm = "error"
    actor_norm = str(actor_type).strip().lower()
    if actor_norm not in ("user", "system", "worker", "skill", "integration", "agent", "api"):
        actor_norm = "system"

    entry = AuditLog(
        user_id=user_id,
        actor_type=actor_norm,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        decision=decision_norm,
        metadata_redacted=redact(metadata or {}),
    )
    session.add(entry)
    await session.flush()
    logger.info(
        "audit action=%s decision=%s user=%s resource=%s/%s",
        action, decision, user_id, resource_type, resource_id,
    )
    return entry

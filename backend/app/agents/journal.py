"""Journal d'exécution : une ligne par fait observé, jamais bloquant.

Écrire le journal ne doit jamais faire échouer une mission : en cas d'erreur
d'écriture, on continue et on le signale dans les logs. Les arguments d'outils
sont expurgés avant stockage (aucun jeton, aucune clé).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.db.models import RunEvent, ToolInvocation

logger = logging.getLogger("kwes.agents.journal")

SENSITIVE_KEYS = ("token", "secret", "password", "api_key", "apikey", "authorization", "cookie")
MAX_ARGS_CHARS = 2000


def redact(value: Any, depth: int = 0) -> Any:
    """Retire les secrets et borne la taille avant journalisation."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in SENSITIVE_KEYS):
                out[str(key)] = "[REDACTED]"
            else:
                out[str(key)] = redact(item, depth + 1)
        return out
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:400]
    return value


class RunJournal:
    """Journal adossé à la base, ouvert pour une mission d'un tenant."""

    def __init__(self, db: Any, *, tenant_id: uuid.UUID, mission_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.mission_id = mission_id

    async def event(
        self,
        event_type: str,
        *,
        status: str | None = None,
        agent_task_id: uuid.UUID | None = None,
        agent_id: str | None = None,
        tool_id: str | None = None,
        duration_ms: int | None = None,
        attempt: int = 0,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        error_code: str | None = None,
        evidence_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            async with self.db.session() as session:
                session.add(
                    RunEvent(
                        tenant_id=self.tenant_id,
                        mission_id=self.mission_id,
                        agent_task_id=agent_task_id,
                        agent_id=agent_id,
                        tool_id=tool_id,
                        event_type=event_type,
                        status=status,
                        duration_ms=duration_ms,
                        attempt=attempt,
                        correlation_id=correlation_id,
                        idempotency_key=idempotency_key,
                        error_code=error_code,
                        evidence_ref=evidence_ref,
                        safe_metadata=redact(metadata or {}),
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - le journal ne casse jamais l'exécution
            logger.exception("Écriture du journal impossible (%s)", event_type)

    async def tool(
        self,
        scope: Any,
        tool_id: str,
        arguments: dict[str, Any],
        status: str,
        *,
        duration_ms: int | None = None,
        error_code: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        from app.agents.runtime import _digest  # import tardif : évite un cycle

        try:
            async with self.db.session() as session:
                session.add(
                    ToolInvocation(
                        tenant_id=scope.tenant_id,
                        mission_id=scope.mission_id,
                        agent_task_id=scope.agent_task_id,
                        agent_id=None,
                        tool_id=tool_id,
                        arguments=redact(arguments),
                        status=status,
                        error_code=error_code,
                        duration_ms=duration_ms,
                        output_digest=_digest(output) if output else None,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Journalisation de l'outil %s impossible", tool_id)

        await self.event(
            "tool.invoked",
            status=status,
            agent_task_id=scope.agent_task_id,
            tool_id=tool_id,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata={"arguments": redact(arguments)},
        )


class Timer:
    """Mesure simple pour les événements."""

    def __init__(self) -> None:
        self.started = time.monotonic()

    @property
    def ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

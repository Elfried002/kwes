"""Écriture des consommations LLM en base.

Le tampon de `app.agent.usage` est vidé ici, dans la transaction de l'appelant :
une réponse n'est jamais bloquée par une erreur d'instrumentation.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import usage
from app.db.models import LLMUsage

logger = logging.getLogger("kwes.usage")


async def flush(session: AsyncSession) -> int:
    """Écrit les mesures accumulées ; renvoie le nombre de lignes écrites."""
    records = usage.drain()
    if not records:
        return 0
    try:
        for record in records:
            session.add(LLMUsage(**record.as_dict()))
        await session.flush()
        return len(records)
    except Exception as exc:  # noqa: BLE001 — l'instrumentation ne casse rien
        logger.warning("Enregistrement des consommations impossible : %s", type(exc).__name__)
        return 0

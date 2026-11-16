"""Verrou d'exécution des tâches, porté par PostgreSQL (source de vérité).

Le verrou évite qu'une même tâche soit exécutée deux fois en parallèle, y compris
entre deux processus worker. Il ne garantit pas l'exécution *exactement une fois* :
si un worker meurt pendant une étape, l'étape sera rejouée après reprise. Les
étapes déjà terminées ne sont jamais rejouées (vérifié par l'orchestrateur).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, update

from app.core.utils import utcnow
from app.db.base import Database
from app.db.models import Task

RUNNABLE_STATUSES = ("queued", "planning", "running")


async def claim_task(
    db: Database, task_id: uuid.UUID, owner: str, ttl_seconds: int
) -> bool:
    """Réserve la tâche pour ``owner``. Renvoie False si un autre la détient."""
    cutoff = utcnow() - timedelta(seconds=ttl_seconds)
    async with db.session() as session:
        result = await session.execute(
            update(Task)
            .where(Task.id == task_id)
            .where(Task.status.in_(RUNNABLE_STATUSES))
            .where(
                or_(
                    Task.claimed_by.is_(None),
                    Task.claimed_by == owner,
                    Task.claimed_at.is_(None),
                    Task.claimed_at < cutoff,
                )
            )
            .values(claimed_by=owner, claimed_at=utcnow())
            .returning(Task.id)
        )
        claimed = result.first() is not None
        await session.commit()
    return claimed


async def release_task(db: Database, task_id: uuid.UUID, owner: str) -> None:
    """Libère le verrou si (et seulement si) c'est bien ``owner`` qui le détient."""
    async with db.session() as session:
        await session.execute(
            update(Task)
            .where(Task.id == task_id, Task.claimed_by == owner)
            .values(claimed_by=None, claimed_at=None)
        )
        await session.commit()


async def release_all(db: Database, owner: str) -> int:
    """Libère tous les verrous d'un worker (appelé à l'arrêt propre)."""
    async with db.session() as session:
        result = await session.execute(
            update(Task)
            .where(Task.claimed_by == owner)
            .values(claimed_by=None, claimed_at=None)
            .returning(Task.id)
        )
        released = len(result.all())
        await session.commit()
    return released

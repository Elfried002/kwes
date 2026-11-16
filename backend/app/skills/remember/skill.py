"""Skill remember — mémorise un fait durable, scopé à l'utilisateur du contexte.

Écriture locale réversible (R1). Aucune action externe, aucun réseau.
Un même fait (comparaison insensible à la casse et aux espaces) met à jour la
ligne existante au lieu de créer un doublon : la mémoire reste lisible.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from contextlib import asynccontextmanager

from sqlalchemy import func, select

from app.db.models import Memory
from app.skills.base import SkillContext, SkillError, SkillResult, SkillValidationError

CATEGORIES = {"working", "episodic", "semantic", "procedural"}
SENSITIVITIES = {"normal", "personal", "sensitive"}
MAX_FACT_CHARS = 2000


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@asynccontextmanager
async def _session_for(ctx: SkillContext):
    """Réutilise la transaction de l'appelant si elle existe (chat)."""
    if ctx.session is not None:
        yield ctx.session
        return
    if ctx.db is None:
        raise SkillError("Mémoire indisponible : base de données non attachée au contexte.")
    async with ctx.db.session() as session:
        yield session


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    fact = _normalize(str(payload.get("fact") or ""))
    if len(fact) < 3:
        raise SkillValidationError("Le fait à retenir est trop court.")
    if len(fact) > MAX_FACT_CHARS:
        fact = fact[:MAX_FACT_CHARS].rstrip() + "…"

    category = str(payload.get("category") or "semantic")
    if category not in CATEGORIES:
        raise SkillValidationError(
            "Catégorie de mémoire invalide.", details={"allowed": sorted(CATEGORIES)}
        )
    sensitivity = str(payload.get("sensitivity") or "normal")
    if sensitivity not in SENSITIVITIES:
        raise SkillValidationError(
            "Niveau de sensibilité invalide.", details={"allowed": sorted(SENSITIVITIES)}
        )
    confidence = payload.get("confidence")
    confidence = 0.8 if confidence is None else max(0.0, min(1.0, float(confidence)))

    async with _session_for(ctx) as session:
        existing = (
            await session.execute(
                select(Memory).where(
                    Memory.user_id == ctx.user_id,
                    func.lower(func.trim(Memory.content)) == fact.lower(),
                )
            )
        ).scalars().first()

        if existing is not None:
            existing.category = category
            existing.sensitivity = sensitivity
            existing.confidence = confidence
            memory = existing
            status = "updated"
        else:
            memory = Memory(
                user_id=ctx.user_id,
                category=category,
                content=fact,
                source_type="agent",
                confidence=confidence,
                sensitivity=sensitivity,
            )
            session.add(memory)
            status = "created"
        await session.commit()
        memory_id = str(memory.id)

    ctx.logger.info("remember status=%s category=%s user=%s", status, category, ctx.user_id)
    label = "retenu" if status == "created" else "mis à jour"
    return SkillResult(
        output={
            "status": status,
            "memory_id": memory_id,
            "category": category,
            "sensitivity": sensitivity,
            "chars": len(fact),
        },
        summary=f"Fait {label} en mémoire ({category}).",
        evidence=[{"type": "memory", "id": memory_id, "category": category}],
    )

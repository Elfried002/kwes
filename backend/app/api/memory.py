"""Mémoire utilisateur : lecture, mise à jour, suppression (filtre user strict)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import PageDep, SessionDep, TenantDep, UserDep
from app.api.serializers import memory_dict
from app.core.errors import NotFound
from app.core.utils import truncate, utcnow
from app.db.models import Memory

router = APIRouter(tags=["memory"])

MEMORY_CATEGORIES = {"working", "episodic", "semantic", "procedural"}
SENSITIVITIES = {"normal", "personal", "sensitive"}


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = None
    sensitivity: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


async def _owned_memory(session, tenant, memory_id: uuid.UUID) -> Memory:
    row = await session.get(Memory, memory_id)
    if row is None or row.tenant_id != tenant.id:
        raise NotFound("Élément de mémoire introuvable.")
    return row


@router.get("/memory")
async def list_memory(
    response: Response,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    page: PageDep,
    category: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
) -> list[dict[str, Any]]:
    stmt = select(Memory).where(Memory.tenant_id == tenant.id)
    if category:
        stmt = stmt.where(Memory.category == category)
    if q:
        pattern = f"%{truncate(q, 120)}%"
        stmt = stmt.where(or_(Memory.content.ilike(pattern), Memory.category.ilike(pattern)))
    rows = (
        await session.execute(
            stmt.order_by(Memory.updated_at.desc()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(Memory.id)).where(Memory.tenant_id == tenant.id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [memory_dict(row) for row in rows]


@router.patch("/memory/{memory_id}")
async def update_memory(
    memory_id: uuid.UUID, payload: MemoryUpdate, user: UserDep, tenant: TenantDep, session: SessionDep
) -> dict[str, Any]:
    row = await _owned_memory(session, tenant, memory_id)
    if payload.category is not None:
        if payload.category not in MEMORY_CATEGORIES:
            from app.core.errors import ValidationFailed

            raise ValidationFailed(
                "Catégorie de mémoire invalide.",
                {"allowed": sorted(MEMORY_CATEGORIES)},
            )
        row.category = payload.category
    if payload.sensitivity is not None:
        if payload.sensitivity not in SENSITIVITIES:
            from app.core.errors import ValidationFailed

            raise ValidationFailed(
                "Niveau de sensibilité invalide.", {"allowed": sorted(SENSITIVITIES)}
            )
        row.sensitivity = payload.sensitivity
    if payload.content is not None:
        row.content = payload.content
    if payload.confidence is not None:
        row.confidence = payload.confidence
    row.updated_at = utcnow()
    await session.commit()
    return memory_dict(row)


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, user: UserDep, tenant: TenantDep, session: SessionDep) -> Response:
    row = await _owned_memory(session, tenant, memory_id)
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)

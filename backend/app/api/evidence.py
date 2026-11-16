"""Preuves de lecture : consultation des sources réellement récupérées.

Lecture seule. Un utilisateur ne voit que ses propres preuves (filtre applicatif
`user_id` + RLS en base).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import DatabaseDep, UserDep
from app.research.evidence import list_for_user

router = APIRouter(tags=["evidence"])


@router.get("/evidence")
async def list_evidence(
    user: UserDep,
    db: DatabaseDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    rows = await list_for_user(db, user.id, limit=limit)
    return {"items": rows, "count": len(rows)}

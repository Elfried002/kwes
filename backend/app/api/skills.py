"""Skills : catalogue actif (activation/désactivation hors routes utilisateur)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import PageDep, SessionDep, UserDep
from app.api.serializers import skill_dict
from app.core.errors import NotFound
from app.db.models import Skill

router = APIRouter(tags=["skills"])


@router.get("/skills")
async def list_skills(
    response: Response, user: UserDep, session: SessionDep, page: PageDep
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Skill).order_by(Skill.name.asc()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    response.headers["X-Total-Count"] = str(len(rows))
    return [skill_dict(row) for row in rows]


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, user: UserDep, session: SessionDep) -> dict[str, Any]:
    row: Skill | None = None
    try:
        identifier = uuid.UUID(skill_id)
    except ValueError:
        identifier = None
    if identifier is not None:
        row = await session.get(Skill, identifier)
    if row is None:
        row = (
            await session.execute(select(Skill).where(Skill.name == skill_id))
        ).scalar_one_or_none()
    if row is None:
        raise NotFound("Skill introuvable.")
    return skill_dict(row)

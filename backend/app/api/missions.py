"""Missions agentiques : lancement, suivi, annulation, reprise.

Une mission est un `Task` (compatibilité) enrichi d'un graphe de tâches
déléguées. Seul le demandeur voit sa mission ; le tenant est posé par le serveur.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.agents.service import MissionService, mission_snapshot
from app.api.deps import PageDep, SessionDep, TenantDep, UserDep
from app.core.errors import NotFound
from app.db.models import AgentTask, Task

router = APIRouter(tags=["missions"])


class MissionCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=4000)
    language: str = Field(default="fr", pattern=r"^(fr|en)$")


class MissionOut(BaseModel):
    id: str
    status: str
    title: str


def _service(request: Request) -> MissionService:
    service = getattr(request.app.state, "missions", None)
    if service is None:
        raise NotFound("Le service de missions n'est pas initialisé.")
    return service


@router.post("/missions", status_code=201, response_model=MissionOut)
async def create_mission(
    payload: MissionCreate,
    request: Request,
    session: SessionDep,
    user: UserDep,
    tenant: TenantDep,
) -> MissionOut:
    mission = Task(
        tenant_id=tenant.id,
        user_id=user.id,
        title=payload.objective.strip()[:200],
        goal=payload.objective.strip(),
        status="queued",
        priority=2,
    )
    session.add(mission)
    await session.commit()
    await session.refresh(mission)

    service = _service(request)
    started = service.start(mission.id, user_id=user.id, tenant_id=tenant.id)
    return MissionOut(
        id=str(mission.id), status="queued" if started else "running", title=mission.title
    )


@router.get("/missions")
async def list_missions(
    session: SessionDep,
    user: UserDep,
    page: PageDep,
) -> dict[str, Any]:
    requete = (
        select(Task)
        .where(Task.user_id == user.id)
        .order_by(desc(Task.created_at))
        .offset(page.offset)
        .limit(page.limit)
    )
    missions = (await session.execute(requete)).scalars().all()
    return {
        "items": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "summary": (m.result_summary or "")[:200],
            }
            for m in missions
        ],
        "limit": page.limit,
        "offset": page.offset,
    }


@router.get("/missions/{mission_id}")
async def get_mission(
    mission_id: uuid.UUID,
    request: Request,
    user: UserDep,
) -> dict[str, Any]:
    vue = await mission_snapshot(request.app.state.db, mission_id, user.id)
    if vue is None:
        raise NotFound("Mission introuvable.")
    vue["running"] = mission_id in getattr(_service(request), "_running", {})
    return vue


@router.post("/missions/{mission_id}/cancel")
async def cancel_mission(
    mission_id: uuid.UUID,
    session: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    mission = await session.get(Task, mission_id)
    if mission is None or mission.user_id != user.id:
        raise NotFound("Mission introuvable.")
    if mission.status in {"completed", "failed", "cancelled"}:
        return {"id": str(mission.id), "status": mission.status, "cancelled": False}
    mission.status = "cancelled"
    taches = (
        await session.execute(
            select(AgentTask).where(
                AgentTask.mission_id == mission_id,
                AgentTask.status.in_(("pending", "ready", "running", "retry_wait")),
            )
        )
    ).scalars().all()
    for tache in taches:
        tache.status = "cancelled"
    await session.commit()
    return {"id": str(mission.id), "status": "cancelled", "cancelled": True, "tasks": len(taches)}


@router.post("/missions/{mission_id}/resume")
async def resume_mission(
    mission_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    user: UserDep,
    tenant: TenantDep,
) -> dict[str, Any]:
    """Reprend une mission interrompue : les tâches terminées ne sont pas rejouées."""
    mission = await session.get(Task, mission_id)
    if mission is None or mission.user_id != user.id:
        raise NotFound("Mission introuvable.")
    if mission.status in {"running", "planning"}:
        return {"id": str(mission.id), "status": mission.status, "resumed": False}

    taches = (
        await session.execute(select(AgentTask).where(AgentTask.mission_id == mission_id))
    ).scalars().all()
    a_rejouer = [t for t in taches if t.status not in {"completed", "cancelled"}]
    for tache in a_rejouer:
        tache.status = "pending"
        tache.error_code = None
    mission.status = "queued"
    mission.error_code = None
    await session.commit()

    started = _service(request).start(mission_id, user_id=user.id, tenant_id=tenant.id)
    return {
        "id": str(mission.id),
        "status": "queued" if started else mission.status,
        "resumed": started,
        "tasks_to_replay": len(a_rejouer),
    }

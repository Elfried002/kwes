"""Missions : création, lecture, annulation, pause, reprise. Propriété vérifiée."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import OrchestratorDep, PageDep, SessionDep, TenantDep, UserDep
from app.api.serializers import task_dict
from app.core.errors import NotFound
from app.db.models import Task

router = APIRouter(tags=["tasks"])

TASK_STATUSES = {
    "queued",
    "planning",
    "awaiting_approval",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
}


class TaskStepCreate(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    skill: str = Field(min_length=3, max_length=64)
    title: str | None = Field(default=None, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    risk: str | None = Field(default=None, pattern=r"^R[0-4]$")
    depends_on: list[str] = Field(default_factory=list)


class TaskCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    title: str | None = Field(default=None, max_length=200)
    conversation_id: uuid.UUID | None = None
    priority: int = Field(default=2, ge=0, le=5)
    steps: list[TaskStepCreate] | None = Field(default=None, max_length=8)


async def _owned_task(session, tenant, task_id: uuid.UUID, *, with_steps: bool = False) -> Task:
    options = [selectinload(Task.steps)] if with_steps else []
    task = await session.get(Task, task_id, options=options)
    if task is None or task.tenant_id != tenant.id:
        raise NotFound("Mission introuvable.")
    return task


@router.post("/tasks", status_code=201)
async def create_task(
    payload: TaskCreate,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    task = await orchestrator.create_task(
        session,
        user,
        goal=payload.goal,
        title=payload.title,
        conversation_id=payload.conversation_id,
        priority=payload.priority,
        raw_steps=[step.model_dump() for step in payload.steps] if payload.steps else None,
    )
    await session.refresh(task, attribute_names=["steps"])
    return task_dict(task, include_steps=True)


@router.get("/tasks")
async def list_tasks(
    response: Response,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    page: PageDep,
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    stmt = select(Task).where(Task.tenant_id == tenant.id)
    if status:
        if status not in TASK_STATUSES:
            status = "__invalid__"
        stmt = stmt.where(Task.status == status)
    rows = (
        await session.execute(
            stmt.order_by(Task.created_at.desc()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(Task.id)).where(
                Task.tenant_id == tenant.id, *([Task.status == status] if status else [])
            )
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [task_dict(row) for row in rows]


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: uuid.UUID, user: UserDep, tenant: TenantDep, session: SessionDep
) -> dict[str, Any]:
    task = await _owned_task(session, tenant, task_id, with_steps=True)
    return task_dict(task, include_steps=True)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    task = await _owned_task(session, tenant, task_id, with_steps=True)
    task = await orchestrator.cancel_task(session, user, task)
    return task_dict(task, include_steps=True)


@router.post("/tasks/{task_id}/pause")
async def pause_task(
    task_id: uuid.UUID,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    task = await _owned_task(session, tenant, task_id, with_steps=True)
    task = await orchestrator.pause_task(session, user, task)
    return task_dict(task, include_steps=True)


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: uuid.UUID,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    task = await _owned_task(session, tenant, task_id, with_steps=True)
    task = await orchestrator.resume_task(session, user, task)
    return task_dict(task, include_steps=True)

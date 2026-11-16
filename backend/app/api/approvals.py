"""Approbations : liste, approbation, refus (expiration + hash de charge utile)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.api.deps import OrchestratorDep, PageDep, SessionDep, UserDep
from app.api.serializers import approval_dict, task_dict
from app.core.errors import NotFound
from app.db.models import Approval, Task

router = APIRouter(tags=["approvals"])

APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired", "consumed"}


async def _owned_approval(session, user, approval_id: uuid.UUID) -> Approval:
    row = await session.get(Approval, approval_id)
    if row is None or row.user_id != user.id:
        raise NotFound("Approbation introuvable.")
    return row


@router.get("/approvals")
async def list_approvals(
    response: Response,
    user: UserDep,
    session: SessionDep,
    page: PageDep,
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    stmt = select(Approval).where(Approval.user_id == user.id)
    if status:
        stmt = stmt.where(Approval.status == (status if status in APPROVAL_STATUSES else "__invalid__"))
    rows = (
        await session.execute(
            stmt.order_by(Approval.expires_at.asc().nulls_last()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(Approval.id)).where(Approval.user_id == user.id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [approval_dict(row) for row in rows]


async def _decide(
    approval_id: uuid.UUID,
    *,
    approve: bool,
    user,
    session,
    orchestrator,
) -> dict[str, Any]:
    approval = await _owned_approval(session, user, approval_id)
    result = await orchestrator.decide_approval(session, user, approval, approve=approve)
    body: dict[str, Any] = {"approval": result, "task": None}
    if approval.task_id is not None:
        task = await session.get(Task, approval.task_id)
        if task is not None and task.user_id == user.id:
            body["task"] = task_dict(task)
    return body


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: uuid.UUID,
    user: UserDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    return await _decide(approval_id, approve=True, user=user, session=session, orchestrator=orchestrator)


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: uuid.UUID,
    user: UserDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    return await _decide(approval_id, approve=False, user=user, session=session, orchestrator=orchestrator)

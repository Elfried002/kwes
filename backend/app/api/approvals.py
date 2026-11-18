"""Approbations : liste, approbation, refus (expiration + hash de charge utile)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.api.deps import OrchestratorDep, PageDep, SessionDep, TenantDep, UserDep
from app.api.serializers import approval_dict, task_dict
from app.core.errors import NotFound
from app.db.models import Approval, Task

router = APIRouter(tags=["approvals"])

APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired", "consumed"}


async def _owned_approval(session, tenant, approval_id: uuid.UUID) -> Approval:
    row = await session.get(Approval, approval_id)
    if row is None or row.tenant_id != tenant.id:
        raise NotFound("Approbation introuvable.")
    return row


@router.get("/approvals")
async def list_approvals(
    response: Response,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    page: PageDep,
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    stmt = select(Approval).where(Approval.tenant_id == tenant.id)
    if status:
        stmt = stmt.where(Approval.status == (status if status in APPROVAL_STATUSES else "__invalid__"))
    rows = (
        await session.execute(
            stmt.order_by(Approval.expires_at.asc().nulls_last()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(Approval.id)).where(Approval.tenant_id == tenant.id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [approval_dict(row) for row in rows]


async def _decide(
    approval_id: uuid.UUID,
    *,
    approve: bool,
    user,
    tenant,
    session,
    orchestrator,
) -> dict[str, Any]:
    approval = await _owned_approval(session, tenant, approval_id)
    result = await orchestrator.decide_approval(session, user, approval, approve=approve)
    body: dict[str, Any] = {"approval": result, "task": None}
    if approval.task_id is not None:
        task = await session.get(Task, approval.task_id)
        if task is not None and task.tenant_id == tenant.id:
            body["task"] = task_dict(task)
    return body


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: uuid.UUID,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    return await _decide(approval_id, approve=True, user=user, tenant=tenant, session=session, orchestrator=orchestrator)


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: uuid.UUID,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    return await _decide(approval_id, approve=False, user=user, tenant=tenant, session=session, orchestrator=orchestrator)

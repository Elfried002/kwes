"""Notifications utilisateur (lecture seule dans le périmètre P0)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, TenantDep, UserDep
from app.api.serializers import notification_dict
from app.db.models import Notification

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    response: Response,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    page: PageDep,
    unread_only: bool = Query(default=False),
) -> list[dict[str, Any]]:
    stmt = select(Notification).where(Notification.tenant_id == tenant.id, Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (
        await session.execute(
            stmt.order_by(Notification.created_at.desc()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(Notification.id)).where(Notification.tenant_id == tenant.id, Notification.user_id == user.id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [notification_dict(row) for row in rows]

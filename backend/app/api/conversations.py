"""Conversations et messages (propriété vérifiée sur chaque route)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.api.deps import PageDep, SessionDep, UserDep
from app.api.serializers import conversation_dict, message_dict
from app.core.errors import NotFound
from app.db.models import Conversation, Message, Task

router = APIRouter(tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=16)


async def _owned_conversation(session, user, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFound("Conversation introuvable.")
    return conversation


@router.get("/conversations")
async def list_conversations(
    response: Response,
    user: UserDep,
    session: SessionDep,
    page: PageDep,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).scalars().all()

    counts: dict[uuid.UUID, int] = {}
    if rows:
        count_rows = (
            await session.execute(
                select(Message.conversation_id, func.count(Message.id))
                .where(Message.conversation_id.in_([r.id for r in rows]))
                .group_by(Message.conversation_id)
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in count_rows}

    total = (
        await session.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [conversation_dict(row, message_count=counts.get(row.id, 0)) for row in rows]


@router.post("/conversations", status_code=201)
async def create_conversation(
    payload: ConversationCreate, user: UserDep, session: SessionDep
) -> dict[str, Any]:
    conversation = Conversation(
        user_id=user.id,
        title=(payload.title or "Nouvelle conversation")[:200],
        language=(payload.language or "fr")[:16],
        status="active",
    )
    session.add(conversation)
    await session.commit()
    return conversation_dict(conversation, message_count=0)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, user: UserDep, session: SessionDep
) -> dict[str, Any]:
    conversation = await _owned_conversation(session, user, conversation_id)
    count = (
        await session.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
        )
    ).scalar_one()
    return conversation_dict(conversation, message_count=int(count))


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    response: Response,
    user: UserDep,
    session: SessionDep,
    page: PageDep,
) -> list[dict[str, Any]]:
    await _owned_conversation(session, user, conversation_id)
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.user_id == user.id)
            .order_by(Message.created_at.asc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(
            select(func.count(Message.id)).where(
                Message.conversation_id == conversation_id, Message.user_id == user.id
            )
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [message_dict(row) for row in rows]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, user: UserDep, session: SessionDep
) -> Response:
    conversation = await _owned_conversation(session, user, conversation_id)
    # Données dérivées : messages supprimés (cascade ORM), missions détachées.
    await session.execute(
        update(Task).where(Task.conversation_id == conversation.id).values(conversation_id=None)
    )
    await session.delete(conversation)
    await session.commit()
    return Response(status_code=204)

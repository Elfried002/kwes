"""POST /chat — conversation et/ou création de mission."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import OrchestratorDep, SessionDep, UserDep

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    language: str | None = Field(default=None, max_length=16)
    mode: Literal["auto", "direct", "mission"] = "auto"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    user: UserDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> dict[str, Any]:
    outcome = await orchestrator.handle_chat(
        session,
        user,
        message=payload.message,
        conversation_id=payload.conversation_id,
        language=payload.language,
        mode=payload.mode,
    )
    body: dict[str, Any] = {
        "conversation_id": str(outcome.conversation.id),
        "message_id": str(outcome.assistant_message.id),
        "response": outcome.response,
        "status": outcome.task.status if outcome.task is not None else "completed",
        "intent": outcome.intent,
    }
    if outcome.task is not None:
        body["task_id"] = str(outcome.task.id)
    return body

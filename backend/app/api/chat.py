"""POST /chat — conversation et/ou création de mission.

POST /chat/stream — même contrat d'entrée, réponse en Server-Sent Events
(`delta` / `done` / `error`). Réutilise l'orchestrateur : aucun second chemin
de persistance, aucune duplication du prompt.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import Orchestrator
from app.api.deps import OrchestratorDep, SessionDep, UserDep
from app.core.errors import ValidationFailed
from app.core.security import CurrentUser

logger = logging.getLogger("kwes.chat")

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Empêche la bufferisation par un proxy (nginx) : indispensable au temps réel.
    "X-Accel-Buffering": "no",
}


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    language: str | None = Field(default=None, max_length=16)
    mode: Literal["auto", "direct", "outil", "mission"] = "auto"


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


def sse_frame(event: str, data: dict[str, Any]) -> str:
    """Encode un événement SSE (une ligne `data:` = un JSON compact)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_events(
    orchestrator: Orchestrator,
    session: AsyncSession,
    user: CurrentUser,
    *,
    message: str,
    conversation_id: uuid.UUID | None,
    language: str | None,
    mode: str,
) -> AsyncIterator[str]:
    """Encapsule le générateur de l'orchestrateur en trames SSE."""

    async def generator() -> AsyncIterator[str]:
        try:
            async for item in orchestrator.stream_chat(
                session,
                user,
                message=message,
                conversation_id=conversation_id,
                language=language,
                mode=mode,
            ):
                yield sse_frame(item.event, item.data)
        except Exception:  # pragma: no cover - filet : les détails restent côté serveur
            logger.exception("Flux SSE interrompu par une erreur interne")
            yield sse_frame(
                "error",
                {
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "code": "INTERNAL",
                    "message": "Le flux de réponse a échoué.",
                    "retryable": True,
                },
            )

    return generator()


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    user: UserDep,
    session: SessionDep,
    orchestrator: OrchestratorDep,
) -> StreamingResponse:
    # Les erreurs de contrat (message vide, conversation d'autrui) doivent rester
    # des réponses HTTP classiques : on les déclenche avant l'ouverture du flux.
    if not payload.message.strip():
        raise ValidationFailed("Le message ne peut pas être vide.")
    if payload.conversation_id is not None:
        # La vérification d'appartenance réutilise la règle de l'orchestrateur.
        await orchestrator.get_conversation_for_user(
            session, user, payload.conversation_id
        )

    return StreamingResponse(
        _stream_events(
            orchestrator,
            session,
            user,
            message=payload.message,
            conversation_id=payload.conversation_id,
            language=payload.language,
            mode=payload.mode,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )

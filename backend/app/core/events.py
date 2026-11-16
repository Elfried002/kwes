"""Bus d'événements interne -> WebSocket (une diffusion par utilisateur)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.utils import iso_utc, new_id, utcnow

logger = logging.getLogger("kwes.events")

EVENT_TYPES = {
    "conversation.delta",
    "conversation.completed",
    "task.created",
    "task.updated",
    "task.step.started",
    "task.step.completed",
    "task.awaiting_approval",
    "task.failed",
    "notification.created",
    "system.status",
}

Sender = Callable[[dict[str, Any]], Awaitable[None]]


def envelope(event: str, data: dict[str, Any]) -> dict[str, Any]:
    if event not in EVENT_TYPES:
        raise ValueError(f"Événement hors contrat: {event}")
    return {
        "event": event,
        "event_id": new_id(),
        "timestamp": iso_utc(utcnow()),
        "data": data,
    }


class EventBus:
    """Registre de senders par utilisateur. Ne bloque jamais l'appelant."""

    def __init__(self) -> None:
        self._senders: dict[uuid.UUID, set[Sender]] = {}
        self._lock = asyncio.Lock()
        self._history: dict[uuid.UUID, list[dict[str, Any]]] = {}

    async def register(self, user_id: uuid.UUID, sender: Sender) -> None:
        async with self._lock:
            self._senders.setdefault(user_id, set()).add(sender)

    async def unregister(self, user_id: uuid.UUID, sender: Sender) -> None:
        async with self._lock:
            bucket = self._senders.get(user_id)
            if not bucket:
                return
            bucket.discard(sender)
            if not bucket:
                self._senders.pop(user_id, None)

    def connection_count(self, user_id: uuid.UUID) -> int:
        return len(self._senders.get(user_id, ()))

    async def publish(self, user_id: uuid.UUID, event: str, data: dict[str, Any]) -> dict[str, Any]:
        message = envelope(event, data)
        async with self._lock:
            senders = list(self._senders.get(user_id, ()))
        for sender in senders:
            try:
                await sender(message)
            except Exception as exc:  # une socket morte ne casse pas la tâche
                logger.warning("WS send failed user=%s event=%s err=%s", user_id, event, type(exc).__name__)
                await self.unregister(user_id, sender)
        return message


event_bus = EventBus()

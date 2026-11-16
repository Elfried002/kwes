"""WebSocket authentifié : /api/v1/ws?token=<jwt>.

Sécurité : jeton obligatoire, origin check, rate limit, heartbeat serveur.
Le WS n'est pas une source de vérité : le client se resynchronise par REST.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.errors import ApiError
from app.core.events import envelope, event_bus
from app.core.security import authenticate_token

logger = logging.getLogger("kwes.ws")

router = APIRouter()

POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013


async def _reject(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:  # handshake déjà refusé
        pass


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    app = websocket.app
    settings = app.state.settings

    origin = websocket.headers.get("origin")
    allowed_origins = set(settings.cors_origin_list)
    if origin:
        if origin not in allowed_origins:
            logger.warning("WS origin refusée: %s", origin[:80])
            await _reject(websocket, POLICY_VIOLATION, "origin_not_allowed")
            return
    elif settings.ws_require_origin:
        await _reject(websocket, POLICY_VIOLATION, "origin_required")
        return

    if not token:
        await _reject(websocket, POLICY_VIOLATION, "token_required")
        return

    db = app.state.db
    try:
        async with db.session() as session:
            user = await authenticate_token(token, session, settings)
    except ApiError:
        await _reject(websocket, POLICY_VIOLATION, "unauthenticated")
        return
    except Exception:
        logger.exception("WS auth error")
        await _reject(websocket, POLICY_VIOLATION, "unauthenticated")
        return

    limiter = app.state.rate_limiter
    if settings.rate_limit_enabled:
        allowed, _retry = limiter.check(str(user.id), "ws", settings.rate_limit_per_minute)
        if not allowed:
            await _reject(websocket, TRY_AGAIN_LATER, "rate_limited")
            return

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def sender(message: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    await event_bus.register(user.id, sender)
    try:
        await sender(
            envelope(
                "system.status",
                {
                    "status": "connected",
                    "user_id": str(user.id),
                    "mock_providers": settings.mock_providers(),
                    "heartbeat_seconds": settings.ws_heartbeat_seconds,
                },
            )
        )
    except Exception:
        await event_bus.unregister(user.id, sender)
        return

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(max(5.0, settings.ws_heartbeat_seconds))
            await sender(
                envelope(
                    "system.status",
                    {"status": "ok", "connections": event_bus.connection_count(user.id)},
                )
            )

    heartbeat_task = asyncio.create_task(heartbeat(), name=f"ws-heartbeat-{user.id}")
    try:
        while True:
            raw = await websocket.receive_text()
            if raw.strip().lower() in ("ping", '"ping"'):
                await sender(envelope("system.status", {"status": "ok", "pong": True}))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.info("WS fermé pour user=%s", user.id)
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        await event_bus.unregister(user.id, sender)

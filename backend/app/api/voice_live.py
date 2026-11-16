"""Voix temps réel : jeton d'accès court, WebSocket, pont vers Gemini Live.

Le navigateur ne reçoit jamais la clé Google. Il obtient un **ticket** à usage
unique (60 s, lié à son compte), ouvre la WebSocket avec ce ticket, puis échange
du PCM 16 bits mono : 16 kHz vers nous, 24 kHz vers lui.

Protocole (client → serveur) : start | audio | text | stop_audio | close
Protocole (serveur → client)  : ready | state | audio | transcript | tool |
                                interrupted | usage | error | closed
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import time
import uuid
from typing import Any

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from pydantic import BaseModel, Field

from app.agent.gemini_live import GeminiLiveSession, LiveUnavailable
from app.agent.tools import CHAT_TOOL_NAMES, tool_definitions
from app.api.deps import DatabaseDep, SettingsDep, UserDep
from app.db.models import Memory, VoiceSession
from app.voice_cost import estimate
from app.voice_languages import list_languages, resolve

logger = logging.getLogger("kwes.voice_live")

router = APIRouter(tags=["voice"])

TICKET_TTL_SECONDS = 60
POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013

# Tickets en mémoire : une seule instance Alpha, durée de vie 60 s. Un ticket
# consommé ne peut pas resservir, même en cas de reconnexion navigateur.
_TICKETS: dict[str, tuple[uuid.UUID, float, str | None]] = {}


class TicketRequest(BaseModel):
    language: str | None = Field(default=None, max_length=16)


def _issue_ticket(user_id: uuid.UUID, language: str | None = None) -> str:
    now = time.time()
    for ticket, (_, expiry, _lang) in list(_TICKETS.items()):
        if expiry <= now:
            _TICKETS.pop(ticket, None)
    ticket = secrets.token_urlsafe(32)
    _TICKETS[ticket] = (user_id, now + TICKET_TTL_SECONDS, language)
    return ticket


def _consume_ticket(ticket: str) -> tuple[uuid.UUID, str | None] | None:
    entry = _TICKETS.pop(ticket, None)
    if entry is None:
        return None
    user_id, expiry, language = entry
    if expiry <= time.time():
        return None
    return user_id, language


@router.get("/voice/config")
async def voice_config(settings: SettingsDep) -> dict[str, Any]:
    return {
        "provider": settings.voice_backend,
        "model": settings.google_live_model,
        "voice": settings.google_voice,
        "available": bool(settings.gemini_api_key),
        "input_rate": 16000,
        "output_rate": 24000,
        "max_session_seconds": settings.google_live_max_session_seconds,
        "idle_seconds": settings.google_live_idle_seconds,
        "daily_budget_eur": settings.google_live_daily_budget_eur,
        "languages": list_languages(),
    }


@router.post("/voice/ticket")
async def voice_ticket(user: UserDep, payload: TicketRequest | None = None) -> dict[str, Any]:
    language = resolve(payload.language if payload else None)
    return {
        "ticket": _issue_ticket(user.id, language.code if language else None),
        "expires_in": TICKET_TTL_SECONDS,
        "url": "/api/v1/voice/live",
        "language": language.code if language else None,
    }


async def _spend_today_usd(session, user_id: uuid.UUID) -> float:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(VoiceSession.estimated_usd), 0.0)).where(
                VoiceSession.user_id == user_id, VoiceSession.started_at >= start
            )
        )
    ).scalar_one()
    return float(total or 0.0)


@router.get("/voice/usage")
async def voice_usage(
    user: UserDep,
    settings: SettingsDep,
    database: DatabaseDep,
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    """Durée cumulée, nombre de sessions et coût estimé (jamais une facture)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with database.session() as session:
        rows = (
            await session.execute(
                select(VoiceSession).where(
                    VoiceSession.user_id == user.id, VoiceSession.started_at >= since
                )
            )
        ).scalars().all()
    total_seconds = sum(row.seconds for row in rows)
    total_in = sum(row.audio_in_seconds for row in rows)
    total_out = sum(row.audio_out_seconds for row in rows)
    total_usd = sum(row.estimated_usd for row in rows)
    return {
        "days": days,
        "sessions": len(rows),
        "seconds": round(total_seconds, 1),
        "audio_in_seconds": round(total_in, 1),
        "audio_out_seconds": round(total_out, 1),
        "estimated_usd": round(total_usd, 4),
        "estimated_eur": round(total_usd * 0.92, 4),
        "daily_budget_eur": settings.google_live_daily_budget_eur,
        "note": "Estimation aux tarifs publiés du modèle, pas un montant facturé.",
        "items": [
            {
                "started_at": row.started_at.isoformat(),
                "seconds": round(row.seconds, 1),
                "turns": row.turns,
                "language": row.language,
                "estimated_usd": round(row.estimated_usd, 4),
                "close_reason": row.close_reason,
            }
            for row in rows[-20:]
        ],
    }


async def _memories_for(session, user_id: uuid.UUID, limit: int) -> list[str]:
    rows = (
        await session.execute(
            select(Memory).where(Memory.user_id == user_id).order_by(Memory.updated_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [row.content for row in rows if row.content]


@router.websocket("/voice/live")
async def voice_live(
    websocket: WebSocket,
    ticket: str | None = Query(default=None),
) -> None:
    app = websocket.app
    settings = app.state.settings

    origin = websocket.headers.get("origin")
    if origin and origin not in set(settings.cors_origin_list):
        logger.warning("Voix : origin refusée (%s)", origin[:80])
        await websocket.close(code=POLICY_VIOLATION, reason="origin_not_allowed")
        return

    consumed = _consume_ticket(ticket) if ticket else None
    if consumed is None:
        await websocket.close(code=POLICY_VIOLATION, reason="ticket_required")
        return
    user_id, language = consumed

    if not settings.gemini_api_key:
        await websocket.close(code=TRY_AGAIN_LATER, reason="voice_unavailable")
        return

    await websocket.accept()
    orchestrator = app.state.orchestrator
    registry = app.state.registry
    definitions = tool_definitions(registry)

    async with app.state.db.session() as session:
        memories = await _memories_for(session, user_id, settings.max_memories_in_prompt)
        spent_today = await _spend_today_usd(session, user_id)

    budget_usd = settings.google_live_daily_budget_eur / 0.92
    if spent_today >= budget_usd:
        await websocket.send_json(
            {
                "type": "error",
                "code": "VOICE_BUDGET_REACHED",
                "message": "Le budget vocal du jour est atteint. Il se réinitialise demain.",
            }
        )
        await websocket.close(code=TRY_AGAIN_LATER)
        return

    async def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in CHAT_TOOL_NAMES:
            return {"status": "refused", "summary": "Outil non disponible à la voix.", "output": None}
        return await orchestrator.tool_runner.execute_named(app.state.db, user_id, name, arguments)

    live = GeminiLiveSession(
        settings,
        definitions=definitions,
        memories=memories,
        executor=executor,
        language=language,
    )

    try:
        await live.start()
    except LiveUnavailable as exc:
        await websocket.send_json({"type": "error", "code": "VOICE_UNAVAILABLE", "message": str(exc)})
        await websocket.close(code=TRY_AGAIN_LATER)
        return

    await websocket.send_json(
        {
            "type": "ready",
            "model": settings.google_live_model,
            "voice": settings.google_voice,
            "input_rate": 16000,
            "output_rate": 24000,
            "language": language,
            "max_session_seconds": settings.google_live_max_session_seconds,
        }
    )
    await websocket.send_json({"type": "state", "value": "listening"})

    started = time.monotonic()
    stop = asyncio.Event()

    async def pump_gemini() -> None:
        try:
            async for event in live.events():
                await websocket.send_json({"type": event.type, **event.data})
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).replace("\n", " ")[:300]
            logger.warning("Flux Gemini Live interrompu: %s — %s", type(exc).__name__, detail)
            try:
                await websocket.send_json(
                    {"type": "error", "code": "VOICE_STREAM_ENDED", "message": "Session vocale interrompue."}
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            stop.set()

    async def watchdog() -> None:
        while not stop.is_set():
            await asyncio.sleep(5)
            if live.usage.elapsed > settings.google_live_max_session_seconds:
                await websocket.send_json({"type": "closed", "reason": "max_duration"})
                stop.set()
                return
            if time.monotonic() - live._last_activity > settings.google_live_idle_seconds:  # noqa: SLF001
                await websocket.send_json({"type": "closed", "reason": "idle"})
                stop.set()
                return

    pump = asyncio.create_task(pump_gemini())
    guard = asyncio.create_task(watchdog())

    try:
        while not stop.is_set():
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            kind = str(message.get("type") or "")
            if kind == "audio":
                try:
                    pcm = base64.b64decode(message.get("data") or "", validate=True)
                except Exception:  # noqa: BLE001
                    continue
                await live.send_audio(pcm[:64_000])
            elif kind == "text":
                await live.send_text(str(message.get("text") or ""))
            elif kind == "activity_start":
                await live.activity_start()
            elif kind == "activity_end":
                await live.activity_end()
            elif kind == "stop_audio":
                await live.end_audio()
            elif kind == "close":
                break
            if live.usage.elapsed > settings.google_live_max_session_seconds:
                await websocket.send_json({"type": "closed", "reason": "max_duration"})
                break
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        guard.cancel()
        await live.close()
        pump.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        usage = live.usage.as_dict()
        cost = estimate(usage["audio_in_s"], usage["audio_out_s"])
        logger.info(
            "Session vocale terminée user=%s %s coût estimé %.4f $",
            user_id,
            usage,
            cost.usd,
        )
        try:
            async with app.state.db.session() as session:
                session.add(
                    VoiceSession(
                        user_id=user_id,
                        model=settings.google_live_model,
                        voice=settings.google_voice,
                        language=language,
                        started_at=datetime.fromtimestamp(
                            time.time() - usage["elapsed_s"], tz=timezone.utc
                        ),
                        ended_at=datetime.now(timezone.utc),
                        seconds=usage["elapsed_s"],
                        audio_in_seconds=usage["audio_in_s"],
                        audio_out_seconds=usage["audio_out_s"],
                        turns=usage["turns"],
                        estimated_usd=cost.usd,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.warning("Enregistrement de la session vocale impossible.")

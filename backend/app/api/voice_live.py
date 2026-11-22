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
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from typing import Any

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select, text

from pydantic import BaseModel, Field

from app.agent.gemini_live import GeminiLiveSession, LiveUnavailable
from app.agent.tools import CHAT_TOOL_NAMES, tool_definitions
from app.core.tenancy import set_current_tenant
from app.db.rls import apply_rls_context, rls_applicable
from app.api.deps import DatabaseDep, SettingsDep, UserDep
from app.db.models import Memory, VoiceSession
from app.voice_cost import estimate
from app.voice_languages import list_languages, resolve

logger = logging.getLogger("kwes.voice_live")

router = APIRouter(tags=["voice"])

TICKET_TTL_SECONDS = 300
POLICY_VIOLATION = 1008
TRY_AGAIN_LATER = 1013

# Tickets signés, sans état : l'API tourne en `--workers 2`, et un ticket gardé
# en mémoire n'était reconnu que par le worker qui l'avait émis. Mesuré avant
# correctif : 9 ouvertures sur 12 refusées en 403 (`ticket_required`), soit une
# session vocale qui échoue au démarrage une fois sur quatre après les deux
# tentatives du client. La signature rend le ticket valable sur tous les workers
# et après un redémarrage ; `_USED` ne sert qu'à refuser un rejeu immédiat.
_USED: dict[str, float] = {}


class TicketRequest(BaseModel):
    language: str | None = Field(default=None, max_length=16)


def _ticket_key(settings: Any) -> bytes:
    """Clé de signature dérivée du secret JWT (jamais utilisée telle quelle)."""
    base = (getattr(settings, "jwt_secret", "") or "").encode()
    return hmac.new(base or b"kwes-voice-ticket", b"voice-ticket", hashlib.sha256).digest()


def _sign(body: str, settings: Any) -> str:
    return hmac.new(_ticket_key(settings), body.encode(), hashlib.sha256).hexdigest()[:43]


def _issue_ticket(user_id: uuid.UUID, language: str | None = None, *, settings: Any = None) -> str:
    now = time.time()
    for nonce, expiry in list(_USED.items()):
        if expiry <= now:
            _USED.pop(nonce, None)
    payload = {
        "u": str(user_id),
        "l": language or "fr",
        "e": round(now + TICKET_TTL_SECONDS, 3),
        "n": secrets.token_hex(8),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{body}.{_sign(body, settings)}"


def _consume_ticket(ticket: str, *, settings: Any = None) -> tuple[uuid.UUID, str | None] | None:
    try:
        body, signature = ticket.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(body, settings)):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        user_id = uuid.UUID(str(payload["u"]))
        expiry = float(payload["e"])
        nonce = str(payload["n"])
    except Exception:  # noqa: BLE001 — ticket malformé = ticket refusé
        return None
    if expiry <= time.time() or nonce in _USED:
        return None
    _USED[nonce] = expiry
    return user_id, (str(payload.get("l") or "fr"))


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
async def voice_ticket(
    user: UserDep, settings: SettingsDep, payload: TicketRequest | None = None
) -> dict[str, Any]:
    """Émet un ticket court. La langue par défaut est **le français**.

    Un client qui n'envoie aucune préférence (ou un code inconnu) obtenait un
    ticket sans langue, donc une session sans consigne : c'est par là que la
    conversation partait en espagnol. Le défaut est désormais explicite, et il
    est écrit dans le ticket pour que le journal de session le montre.
    """
    language = resolve(payload.language if payload else None) or resolve("fr")
    code = language.code if language else "fr"
    return {
        "ticket": _issue_ticket(user.id, code, settings=settings),
        "expires_in": TICKET_TTL_SECONDS,
        "url": "/api/v1/voice/live",
        "language": code,
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

    consumed = _consume_ticket(ticket, settings=settings) if ticket else None
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

    history: list[str] = []
    usage_parts: list[dict[str, Any]] = []

    def make_live(mode: str) -> GeminiLiveSession:
        return GeminiLiveSession(
            settings,
            definitions=definitions,
            memories=memories,
            executor=executor,
            language=language,
            mode=mode,
            context_note="\n".join(history[-6:]),
        )

    state: dict[str, Any] = {
        "live": make_live("fast"),
        "mode": "fast",
        # Bascule automatique : on revient au mode rapide dès que la réponse
        # complexe est terminée (le mode ne doit pas rester « collé »).
        "revert_pending": False,
        "answered": False,
        # Reconstruction de la session Gemini : plafonnée pour ne pas boucler.
        "revives": 0,
    }
    live = state["live"]

    try:
        await live.start()
    except LiveUnavailable as exc:
        await websocket.send_json({"type": "error", "code": "VOICE_UNAVAILABLE", "message": str(exc)})
        await websocket.close(code=TRY_AGAIN_LATER)
        return

    await websocket.send_json(
        {
            "type": "ready",
            "model": live.model_name,
            "mode": state["mode"],
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

    async def safe_send(payload: dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001 — le navigateur est parti
            stop.set()

    async def revive(reason: str) -> None:
        """Reconstruit la session Gemini sans couper celle de l'utilisateur.

        Une session Live meurt pour des raisons normales (durée de vie, 1007
        quand un `activity_start` arrive pendant que le modèle élabore encore sa
        réponse, coupure réseau). Avant, la pompe s'arrêtait et l'écran affichait
        « Session vocale interrompue » : la conversation était perdue. Ici on
        rouvre une session et on réinjecte les derniers échanges.
        """
        nonlocal pump
        switching["value"] = True
        state["revives"] += 1
        usage_parts.append(state["live"].usage.as_dict())
        try:
            await state["live"].close()
        except Exception:  # noqa: BLE001
            pass
        state["live"] = make_live(state["mode"])
        try:
            await state["live"].start()
        except LiveUnavailable:
            switching["value"] = False
            await safe_send(
                {
                    "type": "error",
                    "code": "VOICE_UNAVAILABLE",
                    "message": "La voix s'est interrompue. Touchez pour reprendre.",
                }
            )
            stop.set()
            return
        logger.info("Voix : session reconstruite (%s, essai %s)", reason, state["revives"])
        await safe_send({"type": "reconnecting", "reason": reason})
        await safe_send({"type": "state", "value": "listening"})
        pump = asyncio.create_task(pump_gemini())
        switching["value"] = False

    def broken(reason: str) -> bool:
        """Marque la session comme morte et planifie sa reconstruction, une fois."""
        if switching["value"] or stop.is_set():
            return False
        if state["revives"] >= 3:
            asyncio.create_task(
                safe_send(
                    {
                        "type": "error",
                        "code": "VOICE_STREAM_ENDED",
                        "message": "La voix s'est interrompue. Touchez pour reprendre.",
                    }
                )
            )
            stop.set()
            return False
        switching["value"] = True  # le `finally` de la pompe ne doit pas couper
        asyncio.create_task(revive(reason))
        return True

    async def pump_gemini() -> None:
        current = state["live"]
        try:
            async for event in current.events():
                if event.type == "transcript":
                    role = str(event.data.get("role") or "user")
                    text = str(event.data.get("text") or "").strip()
                    if text:
                        history.append(f"{role} : {text[:300]}")
                        del history[:-8]
                        if role == "user" and settings.voice_auto_thinking:
                            await maybe_escalate(text)
                        elif role == "assistant":
                            state["answered"] = True
                elif event.type == "audio":
                    state["answered"] = True
                elif event.type == "state" and event.data.get("value") == "listening":
                    # Fin de tour : si l'on était passé en raisonnement approfondi
                    # pour cette demande, on redescend en mode rapide.
                    if state["revert_pending"] and state["answered"]:
                        state["revert_pending"] = False
                        state["answered"] = False
                        await switch_mode("fast", reason="fin_reponse")
                await websocket.send_json({"type": event.type, **event.data})
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).replace("\n", " ")[:300]
            logger.warning("Flux Gemini Live interrompu: %s — %s", type(exc).__name__, detail)
            if not stop.is_set() and not switching["value"] and broken("gemini_closed"):
                # La reconstruction est planifiée : on ne coupe pas l'utilisateur.
                return
            await safe_send(
                {"type": "error", "code": "VOICE_STREAM_ENDED", "message": "Session vocale interrompue."}
            )
        finally:
            # Une bascule de mode annule volontairement la pompe : dans ce cas on
            # ne doit pas fermer la session vocale de l'utilisateur.
            logger.info(
                "Pompe Gemini terminée (switching=%s, raison=%s, %.1fs)",
                switching["value"],
                "bascule" if switching["value"] else "fin de flux",
                time.monotonic() - started,
            )
            if not switching["value"]:
                stop.set()

    switching = {"value": False}
    THINKING_MARKERS = (
        "analyse", "analyser", "compare", "comparer", "recherche approfondie", "plan",
        "stratégie", "explique en détail", "explique-moi pourquoi", "pourquoi",
        "étude", "synthèse", "rapport", "budget", "calcul", "décision",
    )

    async def maybe_escalate(text: str) -> None:
        """Bascule vers le modèle de raisonnement approfondi sur demande complexe."""
        if state["mode"] == "thinking":
            return
        lowered = text.lower()
        if not any(marker in lowered for marker in THINKING_MARKERS):
            return
        state["revert_pending"] = True
        state["answered"] = False
        await switch_mode("thinking", reason="demande_complexe")

    async def switch_mode(value: str, *, reason: str = "client") -> None:
        """Reconnecte la session Live sur l'autre modèle, en gardant le contexte."""
        nonlocal pump
        target = "thinking" if value == "thinking" else "fast"
        if target == state["mode"]:
            return
        if settings.google_live_thinking_model == settings.google_live_model:
            # Même modèle des deux côtés et aucun `thinking_config` sur la voix :
            # reconnecter la session ne changeait rien à la réponse, mais coûtait
            # 1 à 2 s de silence et l'audio déjà généré. On répond simplement.
            state["mode"] = target
            await websocket.send_json(
                {"type": "mode", "value": target, "model": state["live"].model_name, "reason": reason}
            )
            return
        logger.info("Voix : bascule %s -> %s (%s)", state["mode"], target, reason)
        switching["value"] = True
        pump.cancel()
        try:
            await pump
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        usage_parts.append(state["live"].usage.as_dict())
        await state["live"].close()
        state["live"] = make_live(target)
        state["mode"] = target
        try:
            await state["live"].start()
        except LiveUnavailable:
            # Repli : on revient au mode rapide plutôt que de couper la voix.
            state["live"] = make_live("fast")
            state["mode"] = "fast"
            await state["live"].start()
            await websocket.send_json(
                {"type": "error", "code": "THINKING_UNAVAILABLE", "message": "Mode approfondi indisponible : conversation normale."}
            )
        switching["value"] = False
        await websocket.send_json(
            {"type": "mode", "value": state["mode"], "model": state["live"].model_name, "reason": reason}
        )
        pump = asyncio.create_task(pump_gemini())

    async def watchdog() -> None:
        while not stop.is_set():
            await asyncio.sleep(5)
            if sum(u["elapsed_s"] for u in usage_parts) + state["live"].usage.elapsed > settings.google_live_max_session_seconds:
                await websocket.send_json({"type": "closed", "reason": "max_duration"})
                stop.set()
                return
            if time.monotonic() - state["live"]._last_activity > settings.google_live_idle_seconds:  # noqa: SLF001
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
            try:
                if kind == "audio":
                    try:
                        pcm = base64.b64decode(message.get("data") or "", validate=True)
                    except Exception:  # noqa: BLE001
                        continue
                    await state["live"].send_audio(pcm[:64_000])
                elif kind == "text":
                    text_in = str(message.get("text") or "")
                    if settings.voice_auto_thinking and text_in.strip():
                        await maybe_escalate(text_in)
                    await state["live"].send_text(text_in)
                elif kind == "activity_start":
                    await state["live"].activity_start()
                elif kind == "activity_end":
                    await state["live"].activity_end()
                elif kind == "stop_audio":
                    await state["live"].end_audio()
            except Exception as exc:  # noqa: BLE001 — session Gemini morte
                # 1007 « Request contains an invalid argument » : un
                # `activity_start` arrivé pendant que le modèle élaborait encore
                # sa réponse fermait la session et coupait l'utilisateur. On
                # reconstruit la session Gemini, celle du navigateur reste.
                logger.warning(
                    "Envoi Gemini refusé (%s) : %s — %s",
                    kind,
                    type(exc).__name__,
                    str(exc).replace("\n", " ")[:160],
                )
                if switching["value"] and not stop.is_set():
                    # Reconstruction en cours : la trame est perdue, pas la session.
                    continue
                if not broken(f"send_{kind}"):
                    stop.set()
                    break
                continue
            if kind == "mode":
                requested = str(message.get("value") or "fast")
                if requested == "thinking":
                    # Même en mode explicite, on redescend après la réponse :
                    # le mode approfondi ne doit jamais rester « collé ».
                    state["revert_pending"] = True
                    state["answered"] = False
                await switch_mode(requested)
            if kind == "close":
                break
            if sum(u["elapsed_s"] for u in usage_parts) + state["live"].usage.elapsed > settings.google_live_max_session_seconds:
                await websocket.send_json({"type": "closed", "reason": "max_duration"})
                break
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        guard.cancel()
        await state["live"].close()
        pump.cancel()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        usage_parts.append(state["live"].usage.as_dict())
        usage = {
            "elapsed_s": round(sum(u["elapsed_s"] for u in usage_parts), 1),
            "audio_in_s": round(sum(u["audio_in_s"] for u in usage_parts), 1),
            "audio_out_s": round(sum(u["audio_out_s"] for u in usage_parts), 1),
            "turns": sum(u["turns"] for u in usage_parts),
            "dropped_frames": sum(u.get("dropped_frames", 0) for u in usage_parts),
            "short_turns": sum(u.get("short_turns", 0) for u in usage_parts),
        }
        cost = estimate(usage["audio_in_s"], usage["audio_out_s"])
        logger.info(
            "Session vocale terminée user=%s %s coût estimé %.4f $",
            user_id,
            usage,
            cost.usd,
        )
        try:
            async with app.state.db.session() as session:
                # Cette écriture ouvre sa propre session, hors requête HTTP : sans
                # ce contexte, `auth.uid()` est vide et la politique RLS refuse
                # l'insertion (la session vocale n'était donc jamais enregistrée).
                if rls_applicable(settings, session):
                    await apply_rls_context(session, user_id)
                # La politique d'insertion exige l'appartenance à l'espace : sans
                # `tenant_id`, `is_tenant_member(NULL)` est faux et la ligne est
                # refusée — c'était la vraie cause de la perte des sessions.
                tenant_id = (
                    await session.execute(
                        text(
                            "select tenant_id from tenant_memberships "
                            "where user_id = :user_id order by created_at limit 1"
                        ),
                        {"user_id": user_id},
                    )
                ).scalar()
                set_current_tenant(tenant_id)
                session.add(
                    VoiceSession(
                        user_id=user_id,
                        tenant_id=tenant_id,
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("Enregistrement de la session vocale impossible: %s", str(exc)[:160])

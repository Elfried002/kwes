"""Health check : /health et /api/v1/health (mêmes données)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

logger = logging.getLogger("kwes.health")

router = APIRouter(tags=["health"])


async def _redis_status(settings: Settings) -> str:
    client = Redis.from_url(
        settings.redis_url, socket_connect_timeout=0.4, socket_timeout=0.6
    )
    try:
        await client.ping()
        return "ok"
    except (RedisError, OSError, ValueError):
        return "degraded"
    finally:
        try:
            await client.aclose()
        except Exception:  # pragma: no cover
            pass


async def health_payload(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    database_ok = await request.app.state.db.ping()
    redis_status = await _redis_status(settings)
    llm_status = "degraded" if settings.llm_is_mock else "ok"
    status = "ok" if database_ok else "degraded"
    return {
        "status": status,
        "version": settings.version,
        "dependencies": {
            "database": "ok" if database_ok else "degraded",
            "redis": redis_status,
            "llm": llm_status,
        },
    }


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return await health_payload(request)

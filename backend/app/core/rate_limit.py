"""Rate limiting simple en mémoire (par utilisateur + route).

Suffisant pour l'Alpha mono-instance. En multi-instance, remplacer par Redis
(interface identique). Désactivable via RATE_LIMIT_ENABLED=false (tests).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.errors import RateLimited
from app.core.security import CurrentUser, get_current_user


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window = window_seconds
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, subject: str, scope: str, limit: int) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._hits[(subject, scope)]
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(self.window - (now - bucket[0])) + 1)
            return False, retry_after
        bucket.append(now)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()


def route_scope(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return str(template or request.url.path)


async def enforce_rate_limit(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    settings: Settings = request.app.state.settings
    if not settings.rate_limit_enabled:
        return
    limiter: SlidingWindowLimiter = request.app.state.rate_limiter
    scope = route_scope(request)
    limit = (
        settings.rate_limit_chat_per_minute
        if scope.endswith("/chat")
        else settings.rate_limit_per_minute
    )
    allowed, retry_after = limiter.check(str(user.id), scope, limit)
    if not allowed:
        raise RateLimited(
            "Trop de requêtes, réessayez dans un instant.",
            {"scope": scope, "limit_per_minute": limit, "retry_after_seconds": retry_after},
            retry_after=retry_after,
        )

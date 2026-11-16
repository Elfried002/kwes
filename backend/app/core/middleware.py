"""Middleware HTTP : request-id, limite de taille, en-têtes de mock explicites.

Le middleware est ASGI pur afin de pouvoir ajouter des en-têtes avant l'envoi
de `http.response.start` (donc avant tout streaming).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import error_payload

logger = logging.getLogger("kwes.http")


class KwesHttpMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.mock_providers = settings.mock_providers()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get(self.settings.request_id_header) or str(uuid.uuid4())
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id

        content_length = headers.get("content-length")
        if content_length:
            try:
                too_large = int(content_length) > self.settings.max_request_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                response = JSONResponse(
                    status_code=413,
                    content=error_payload(
                        "VALIDATION_ERROR",
                        "Requête trop volumineuse.",
                        {"max_bytes": self.settings.max_request_body_bytes},
                        request_id,
                    ),
                    headers={"X-Request-ID": request_id},
                )
                await response(scope, receive, send)
                return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                mutable["X-Request-ID"] = request_id
                if self.mock_providers:
                    mutable["X-Kwes-Mock"] = "1"
                    mutable["X-Kwes-Mock-Providers"] = ",".join(self.mock_providers)
                mutable.setdefault(
                    "Cache-Control",
                    "no-store" if scope.get("path", "").startswith(self.settings.api_prefix) else "no-cache",
                )
            await send(message)

        await self.app(scope, receive, send_with_headers)

"""Erreurs applicatives au format du contrat d'intégration.

Format de réponse :
    {"error": {"code", "message", "details", "request_id", "retryable"}}

Codes autorisés par CONTRACTS.md : UNAUTHENTICATED, FORBIDDEN, NOT_FOUND,
VALIDATION_ERROR, PROVIDER_UNAVAILABLE, RATE_LIMITED, APPROVAL_REQUIRED, INTERNAL.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("kwes.errors")

ALLOWED_CODES = {
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "PROVIDER_UNAVAILABLE",
    "RATE_LIMITED",
    "APPROVAL_REQUIRED",
    "INTERNAL",
}


class ApiError(Exception):
    """Erreur métier sérialisée au format contrat."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        if code not in ALLOWED_CODES:
            raise ValueError(f"Code d'erreur hors contrat: {code}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable


class Unauthenticated(ApiError):
    def __init__(self, message: str = "Authentification requise.", details: dict[str, Any] | None = None) -> None:
        super().__init__("UNAUTHENTICATED", message, 401, details)


class Forbidden(ApiError):
    def __init__(self, message: str = "Action non autorisée.", details: dict[str, Any] | None = None) -> None:
        super().__init__("FORBIDDEN", message, 403, details)


class NotFound(ApiError):
    def __init__(self, message: str = "Ressource introuvable.", details: dict[str, Any] | None = None) -> None:
        super().__init__("NOT_FOUND", message, 404, details)


class ValidationFailed(ApiError):
    def __init__(self, message: str = "Requête invalide.", details: dict[str, Any] | None = None) -> None:
        super().__init__("VALIDATION_ERROR", message, 422, details)


class ProviderUnavailable(ApiError):
    def __init__(self, message: str = "Le service est temporairement indisponible.", details: dict[str, Any] | None = None) -> None:
        super().__init__("PROVIDER_UNAVAILABLE", message, 503, details, retryable=True)


class RateLimited(ApiError):
    def __init__(self, message: str = "Trop de requêtes.", details: dict[str, Any] | None = None, retry_after: int = 60) -> None:
        super().__init__("RATE_LIMITED", message, 429, details or {"retry_after_seconds": retry_after})


class ApprovalRequired(ApiError):
    def __init__(self, message: str = "Une approbation est requise.", details: dict[str, Any] | None = None) -> None:
        super().__init__("APPROVAL_REQUIRED", message, 409, details)


class InternalError(ApiError):
    def __init__(self, message: str = "Erreur interne.", details: dict[str, Any] | None = None) -> None:
        super().__init__("INTERNAL", message, 500, details)


def error_payload(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id or str(uuid.uuid4()),
            "retryable": retryable,
        }
    }


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else str(uuid.uuid4())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        headers = {}
        if exc.code == "RATE_LIMITED":
            retry_after = exc.details.get("retry_after_seconds", 60)
            headers["Retry-After"] = str(int(retry_after))
        headers["X-Request-ID"] = _request_id(request)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.details, _request_id(request), exc.retryable),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "loc": ".".join(str(p) for p in err.get("loc", [])),
                "message": str(err.get("msg", "invalid")),
                "type": str(err.get("type", "invalid")),
            }
            for err in exc.errors()[:20]
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "VALIDATION_ERROR",
                "La requête ne respecte pas le schéma attendu.",
                {"fields": fields},
                _request_id(request),
            ),
            headers={"X-Request-ID": _request_id(request)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        mapping = {
            401: ("UNAUTHENTICATED", "Authentification requise."),
            403: ("FORBIDDEN", "Action non autorisée."),
            404: ("NOT_FOUND", "Ressource introuvable."),
            405: ("VALIDATION_ERROR", "Méthode non autorisée."),
            429: ("RATE_LIMITED", "Trop de requêtes."),
        }
        code, message = mapping.get(exc.status_code, ("INTERNAL", "Erreur interne."))
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code, message, {}, _request_id(request)),
            headers={"X-Request-ID": _request_id(request)},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        rid = _request_id(request)
        # Jamais de stack trace ni de message fournisseur dans la réponse.
        logger.exception("Unhandled error request_id=%s path=%s", rid, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL", "Erreur interne.", {}, rid),
            headers={"X-Request-ID": rid},
        )

    # Une panne ou un dépassement de délai du fournisseur LLM n'est pas une
    # erreur interne : c'est un 503 réessayable, comme le fait déjà le flux SSE.
    # Sans ce handler, un LLMTimeout remontait en 500 INTERNAL (traceback
    # `LLMTimeout` observé en production).
    from app.agent.llm import LLMError

    @app.exception_handler(LLMError)
    async def _llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
        rid = _request_id(request)
        logger.warning(
            "Fournisseur LLM indisponible code=%s retryable=%s request_id=%s path=%s",
            exc.code,
            exc.retryable,
            rid,
            request.url.path,
        )
        return JSONResponse(
            status_code=503,
            content=error_payload(
                "PROVIDER_UNAVAILABLE",
                exc.message
                if exc.code in {"PROVIDER_UNAVAILABLE", "INVALID_OUTPUT"}
                else "Le fournisseur LLM n'a pas répondu à temps.",
                {},
                rid,
                retryable=True,
            ),
            headers={"X-Request-ID": rid},
        )

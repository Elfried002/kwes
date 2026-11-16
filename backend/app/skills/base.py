"""Contrat d'exécution des skills (contexte isolé, erreurs typées, résultat)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    elapsed_ms: int = 0
    # Octets d'origine, conservés uniquement pour les binaires documentaires
    # (PDF) : l'extraction PDF (P1) ne peut pas travailler sur du texte décodé.
    raw: bytes | None = None


FetchFn = Callable[[str], Awaitable[FetchedPage]]


@dataclass
class SkillContext:
    user_id: uuid.UUID
    settings: Settings
    fetch: FetchFn
    allowlist: list[str]
    granted_permissions: frozenset[str] = frozenset()
    task_id: uuid.UUID | None = None
    step_id: uuid.UUID | None = None
    timeout_seconds: float = 60.0
    # Accès base borné à l'utilisateur du contexte : seuls les skills qui
    # déclarent `local.write` et écrivent sous `user_id` l'utilisent (mémoire,
    # documents). Absent des contextes sans base (tests unitaires de skill).
    # `session` est la transaction de l'appelant quand elle existe (chat) : la
    # réutiliser évite une seconde transaction concurrente sur la même ligne.
    session: Any | None = None
    db: Any | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("kwes.skills"))


@dataclass
class SkillResult:
    output: dict[str, Any]
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


class SkillError(Exception):
    code = "SKILL_FAILED"
    retryable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SkillValidationError(SkillError):
    code = "SKILL_VALIDATION"


class SkillOutputError(SkillError):
    code = "SKILL_OUTPUT_INVALID"


class SkillPermissionError(SkillError):
    code = "SKILL_FORBIDDEN"


class SkillTimeout(SkillError):
    code = "SKILL_TIMEOUT"
    retryable = True


class SkillProviderError(SkillError):
    code = "PROVIDER_UNAVAILABLE"
    retryable = True


class SkillManifestError(SkillError):
    code = "SKILL_MANIFEST_INVALID"

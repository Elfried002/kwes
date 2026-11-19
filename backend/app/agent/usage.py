"""Instrumentation de la consommation LLM.

Chaque appel texte passe par `GeminiTextClient.chat` : c'est le point unique où
les tokens peuvent être mesurés sans disperser la logique. Les mesures sont
bufferisées dans le contexte de la requête, puis écrites en base par l'appelant
qui dispose d'une session (orchestrateur, worker).

Aucune estimation n'est inventée : si le fournisseur ne renvoie pas les tokens,
la ligne est enregistrée avec des valeurs nulles et un indicateur `source`.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# Contexte de la requête en cours : renseigné par l'orchestrateur ou le worker.
_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("kwes_llm_context", default={})
_BUFFER: ContextVar[list["UsageRecord"]] = ContextVar("kwes_llm_usage", default=[])


@dataclass(slots=True)
class UsageRecord:
    model: str
    provider: str = "google"
    purpose: str = "chat"
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int = 0
    source: str = "provider"  # provider | estimated | unavailable
    tenant_id: uuid.UUID | None = None
    mission_id: uuid.UUID | None = None
    agent_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "purpose": self.purpose,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "source": self.source,
            "tenant_id": self.tenant_id,
            "mission_id": self.mission_id,
            "agent_id": self.agent_id,
        }


def set_context(
    *,
    tenant_id: uuid.UUID | None = None,
    mission_id: uuid.UUID | None = None,
    agent_id: str | None = None,
) -> None:
    """Déclare le contexte d'attribution des consommations à venir."""
    current = dict(_CONTEXT.get())
    if tenant_id is not None:
        current["tenant_id"] = tenant_id
    if mission_id is not None:
        current["mission_id"] = mission_id
    if agent_id is not None:
        current["agent_id"] = agent_id
    _CONTEXT.set(current)


def clear_context() -> None:
    _CONTEXT.set({})


def record(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    purpose: str = "chat",
    duration_ms: int = 0,
    provider: str = "google",
) -> None:
    """Ajoute une mesure au tampon de la requête en cours."""
    context = _CONTEXT.get()
    buffer = list(_BUFFER.get())
    buffer.append(
        UsageRecord(
            model=model,
            provider=provider,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            source="provider" if input_tokens is not None else "unavailable",
            tenant_id=context.get("tenant_id"),
            mission_id=context.get("mission_id"),
            agent_id=context.get("agent_id"),
        )
    )
    _BUFFER.set(buffer)


def drain() -> list[UsageRecord]:
    """Vide le tampon et renvoie les mesures accumulées."""
    buffer = list(_BUFFER.get())
    _BUFFER.set([])
    return buffer


def total(records: list[UsageRecord]) -> dict[str, int]:
    entree = sum(r.input_tokens or 0 for r in records)
    sortie = sum(r.output_tokens or 0 for r in records)
    return {"appels": len(records), "input_tokens": entree, "output_tokens": sortie}


@dataclass(slots=True)
class _Sentinel:
    """Garde-fou de développement : le tampon ne doit pas grossir indéfiniment."""

    max_size: int = 500
    _seen: int = field(default=0)

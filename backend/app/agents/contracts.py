"""Contrats d'échange entre KWES Core et les spécialistes.

Deux objets seulement, volontairement minimalistes :

- `AgentTask` : ce que Core envoie à un spécialiste (aucun privilège implicite) ;
- `AgentResult` : ce que le spécialiste renvoie (résumé, preuves, limites).

Le spécialiste ne reçoit jamais ses permissions du modèle : `allowed_tools` est
calculé par Core à partir du registre et de la politique, et contrôlé au retour.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AUTONOMY = Literal["A0", "A1", "A2", "A3", "A4"]
STATUS = Literal["completed", "partial", "blocked", "failed"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    mission_id: uuid.UUID
    agent_id: str
    objective: str = Field(min_length=3, max_length=2000)
    expected_output: str = Field(min_length=3, max_length=1000)
    context_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    autonomy_level: AUTONOMY = "A1"
    deadline_seconds: int = Field(default=180, ge=1, le=600)
    max_tool_calls: int = Field(default=12, ge=1, le=100)
    dependencies: list[uuid.UUID] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    language: Literal["fr", "en"] = "fr"

    @field_validator("agent_id")
    @classmethod
    def _agent_id(cls, value: str) -> str:
        if not value.startswith("kwes."):
            raise ValueError("agent_id doit commencer par « kwes. »")
        return value


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["source", "fichier", "commande", "mesure", "citation"]
    reference: str
    detail: str | None = None


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    mission_id: uuid.UUID
    agent_id: str
    status: STATUS
    summary: str = Field(min_length=1, max_length=4000)
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    tool_calls: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    completed_at: datetime = Field(default_factory=_now)

    @field_validator("evidence")
    @classmethod
    def _preuve_si_succes(cls, value: list[Evidence]) -> list[Evidence]:
        return value

    def is_verified(self) -> bool:
        """Un résultat « completed » sans preuve n'est pas vérifiable."""
        return self.status == "completed" and len(self.evidence) > 0

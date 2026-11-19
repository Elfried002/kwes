"""Schémas de validation des agents KWES.

Un package d'agents est une donnée d'exécution : il est validé strictement au
chargement, et tout écart fait échouer le chargement complet (fail closed).
Aucun agent partiellement valide n'est exposé au répartiteur.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_MODELS = {
    "gemini-3.8-live",
    "gemini-3.8-live-extended-thinking",
}
AGENT_ID_PATTERN = re.compile(r"^kwes\.[a-z][a-z0-9_]*$")
AUTONOMY_LEVELS = {"A0", "A1", "A2", "A3", "A4"}
APPROVAL_BY_LEVEL = {
    "A0": {"none"},
    "A1": {"none"},
    "A2": {"policy_checked"},
    "A3": {"explicit"},
    "A4": {"strong"},
}
MAX_TIMEOUT_SECONDS = 600
MAX_RETRIES = 3


class Authority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reports_to: str | None = None
    may_dispatch_agents: bool
    may_change_user_permissions: bool
    may_override_policy: bool
    may_execute_outside_domain: bool = False
    # Core peut *demander* un changement de permission à l'utilisateur ; il ne
    # peut pas l'appliquer lui-même (décision du 19/11/2026).
    can_request_permission_change_through_user_approval: bool = False


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="allow")

    declared_tool_ids: list[str] = Field(default_factory=list)
    tool_status: dict[str, Literal["implemented", "declared"]] = Field(default_factory=dict)
    default_tool_access: str | None = None

    @model_validator(mode="after")
    def _statut_pour_chaque_outil(self) -> "Capabilities":
        manquants = [t for t in self.declared_tool_ids if t not in self.tool_status]
        if manquants:
            raise ValueError(
                "Chaque outil déclaré doit porter un statut (implemented|declared) : "
                + ", ".join(sorted(manquants))
            )
        return self


class ApprovalRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["A0", "A1", "A2", "A3", "A4"]
    approval: Literal["none", "policy_checked", "explicit", "strong"]

    @model_validator(mode="after")
    def _coherence_niveau_approbation(self) -> "ApprovalRule":
        attendu = APPROVAL_BY_LEVEL[self.level]
        if self.approval not in attendu:
            raise ValueError(
                f"Niveau {self.level} incompatible avec l'approbation « {self.approval} » "
                f"(attendu : {', '.join(sorted(attendu))})"
            )
        return self


class Isolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_role: Literal["kwes_app"] = "kwes_app"
    rls_context: Literal["per_task"] = "per_task"
    bypass_rls_forbidden: bool = True

    @model_validator(mode="after")
    def _pas_de_contournement(self) -> "Isolation":
        if not self.bypass_rls_forbidden:
            raise ValueError(
                "Un agent ne peut pas exécuter avec un contournement de la RLS "
                "(DB_RLS_BYPASS interdit pour les agents)."
            )
        return self


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quota_source: str = "kwes_existing_quotas"
    max_tool_calls_per_task: int = Field(default=12, ge=1, le=100)
    max_tool_calls_per_mission: int | None = Field(default=None, ge=1, le=500)
    max_wall_clock_seconds_per_task: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_SECONDS)
    max_wall_clock_seconds_per_mission: int | None = Field(default=None, ge=1, le=3600)
    max_cost_eur_per_task: float | None = Field(default=None, ge=0)
    max_cost_eur_per_mission: float | None = Field(default=None, ge=0)
    status: str = "proposal_pending_owner_validation"
    reference: str | None = None


class Execution(BaseModel):
    model_config = ConfigDict(extra="allow")

    timeout_seconds: int = Field(default=180, ge=1, le=MAX_TIMEOUT_SECONDS)
    max_retries: int = Field(default=2, ge=0, le=MAX_RETRIES)
    budget: Budget = Field(default_factory=Budget)
    isolation: Isolation = Field(default_factory=Isolation)


class ModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_models: list[str]
    default_model: str
    reasoning_model: str | None = None
    allow_unlisted_models: bool = False
    automatic_provider_fallback: bool = False
    model_change_requires_user_approval: bool = True

    @model_validator(mode="after")
    def _perimetre_modeles(self) -> "ModelPolicy":
        hors_perimetre = {m for m in self.allowed_models if m not in ALLOWED_MODELS}
        if hors_perimetre:
            raise ValueError(f"Modèles hors périmètre : {', '.join(sorted(hors_perimetre))}")
        if self.default_model not in ALLOWED_MODELS:
            raise ValueError(f"Modèle par défaut hors périmètre : {self.default_model}")
        if self.allow_unlisted_models:
            raise ValueError("allow_unlisted_models doit rester false.")
        if self.automatic_provider_fallback:
            raise ValueError("Le basculement automatique de fournisseur est interdit.")
        return self


class AgentConfig(BaseModel):
    """Configuration d'un agent (KWES Core ou spécialiste)."""

    model_config = ConfigDict(extra="allow")

    agent_id: str
    display_name: str
    agent_type: Literal["orchestrator", "specialist"]
    version: str
    status: Literal["defined_not_activated", "tested", "active", "retired"]
    inherits: str | None = None
    overrides: list[str] = Field(default_factory=list)

    authority: Authority
    capabilities: Capabilities = Field(default_factory=Capabilities)
    approval_matrix: dict[str, ApprovalRule] = Field(default_factory=dict)
    execution: Execution = Field(default_factory=Execution)
    autonomy: dict = Field(default_factory=dict)
    model_policy: ModelPolicy | None = None

    @model_validator(mode="after")
    def _identifiant(self) -> "AgentConfig":
        if not AGENT_ID_PATTERN.match(self.agent_id):
            raise ValueError(f"agent_id invalide : {self.agent_id} (attendu kwes.<slug>)")
        return self

    @model_validator(mode="after")
    def _specialiste_sobre(self) -> "AgentConfig":
        if self.agent_type == "specialist":
            if self.authority.may_dispatch_agents:
                raise ValueError("Un spécialiste ne peut pas distribuer de tâches.")
            if self.authority.may_change_user_permissions:
                raise ValueError("Un spécialiste ne peut pas modifier les permissions.")
            if self.authority.may_override_policy:
                raise ValueError("Un spécialiste ne peut pas contourner la politique.")
        return self

    @model_validator(mode="after")
    def _core_ne_modifie_pas_les_permissions(self) -> "AgentConfig":
        if self.agent_type == "orchestrator" and self.authority.may_change_user_permissions:
            raise ValueError(
                "KWES Core peut demander une autorisation à l'utilisateur, "
                "mais ne peut pas modifier lui-même les permissions."
            )
        return self

    @model_validator(mode="after")
    def _matrice_complete(self) -> "AgentConfig":
        outils = set(self.capabilities.declared_tool_ids)
        if not outils:
            return self
        manquants = sorted(outils - set(self.approval_matrix))
        if manquants:
            raise ValueError(
                "Aucun outil ne peut exister sans niveau d'approbation : "
                + ", ".join(manquants)
            )
        inconnus = sorted(set(self.approval_matrix) - outils)
        if inconnus:
            raise ValueError(
                "La matrice d'approbation cite des outils non déclarés : "
                + ", ".join(inconnus)
            )
        return self

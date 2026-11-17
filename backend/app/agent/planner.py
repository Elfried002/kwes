"""Planificateur : intention -> plan structuré validé (jamais exécuté tel quel)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.agent.llm import LLMClient, LLMError
from app.core.config import Settings
from app.skills.registry import SkillRegistry

logger = logging.getLogger("kwes.planner")

RiskLiteral = Literal["R0", "R1", "R2", "R3", "R4"]


class PlanStep(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_\-]{1,40}$")
    skill: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    title: str | None = Field(default=None, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLiteral = "R0"
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("depends_on")
    @classmethod
    def _deps_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("dépendances dupliquées")
        return value


class Plan(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)
    steps: list[PlanStep] = Field(min_length=1)

    @field_validator("steps")
    @classmethod
    def _ids_unique(cls, value: list[PlanStep]) -> list[PlanStep]:
        ids = [s.id for s in value]
        if len(set(ids)) != len(ids):
            raise ValueError("identifiants d'étapes dupliqués")
        return value


class PlanValidationError(Exception):
    pass


@dataclass
class PlanValidation:
    plan: Plan
    warnings: list[str]


def validate_plan(plan: Plan, registry: SkillRegistry, *, max_steps: int) -> PlanValidation:
    warnings: list[str] = []
    if len(plan.steps) > max_steps:
        raise PlanValidationError(f"Le plan dépasse la limite de {max_steps} étapes.")

    seen: set[str] = set()
    for step in plan.steps:
        if step.skill not in registry.names:
            raise PlanValidationError(f"Skill inconnu ou désactivé: {step.skill}")
        for dependency in step.depends_on:
            if dependency not in seen:
                raise PlanValidationError(
                    f"Dépendance invalide pour {step.id}: {dependency} (doit précéder l'étape)."
                )
        if not isinstance(step.input, dict):
            raise PlanValidationError(f"Entrée non-objet pour {step.id}.")
        if step.risk in ("R3", "R4"):
            warnings.append(f"{step.id} déclare un risque {step.risk} : exécution soumise au policy engine.")
        seen.add(step.id)

    return PlanValidation(plan=plan, warnings=warnings)


SYSTEM_PROMPT = """Tu es le planificateur de Kwes, un agent personnel autonome.
Tu produis un plan d'exécution en JSON strict, exécutable par des skills.

Skills disponibles :
{skills}

Règles :
- 1 à {max_steps} étapes maximum.
- Chaque étape a un identifiant unique (step_1, step_2, ...), un skill existant,
  une entrée conforme au schéma d'entrée du skill, un niveau de risque R0-R4 et
  la liste de ses dépendances (identifiants d'étapes précédentes).
- Ne jamais inventer un skill. Ne jamais demander d'action payante.
- Si la demande attend un livrable (rapport, note, synthèse), l'étape document_write
  doit contenir le texte COMPLET et rédigé dans `content` (plusieurs paragraphes,
  au moins 600 mots pour un rapport) : jamais un résumé d'une phrase.
- Une étape qui dépend d'une autre peut réutiliser son résultat, sans le recopier.
- Si la demande ne nécessite aucune action outil, retourne une seule étape business_planning.
- `input` n'est JAMAIS vide : il contient les champs requis annoncés pour le skill
  (par exemple `query` pour web_research, `title` et `content` pour document_write,
  `objective` pour business_planning).
- Réponds UNIQUEMENT avec un objet JSON, sans texte autour :
  {{"goal": "Objectif reformulé", "steps": [
    {{"id": "step_1", "skill": "web_research", "title": "Rechercher les sources",
      "input": {{"query": "requête précise", "depth": "standard"}},
      "risk": "R0", "depends_on": []}},
    {{"id": "step_2", "skill": "document_write", "title": "Rédiger la note",
      "input": {{"title": "Titre du document", "format": "markdown",
                 "content": "Texte complet et rédigé, plusieurs paragraphes."}},
      "risk": "R1", "depends_on": ["step_1"]}}
  ]}}
"""


def _normalize_inputs(plan: Plan) -> None:
    """Corrige les confusions de champs les plus fréquentes du modèle.

    Un modèle « lite » glisse parfois `key`/`value` (champs de `remember`) dans une
    étape `document_write`. On remet chaque valeur à sa place au lieu d'échouer,
    sans jamais inventer de contenu : si le texte manque vraiment, l'étape échouera
    et la mission le dira.
    """
    for step in plan.steps:
        payload = step.input if isinstance(step.input, dict) else {}
        if step.skill == "document_write":
            if not payload.get("content") and payload.get("value"):
                payload["content"] = payload.pop("value")
            payload.pop("key", None)
        elif step.skill == "remember":
            if not payload.get("value") and payload.get("content"):
                payload["value"] = payload.pop("content")
            if not payload.get("key") and payload.get("title"):
                payload["key"] = payload.pop("title")
        step.input = payload


class Planner:
    def __init__(self, settings: Settings, llm: LLMClient, registry: SkillRegistry) -> None:
        self.settings = settings
        self.llm = llm
        self.registry = registry

    def _drop_unknown_fields(self, plan: Plan) -> None:
        """Retire les champs qu'un skill n'accepte pas.

        Les schémas d'entrée refusent les propriétés inconnues (`additionalProperties:
        false`) : un modèle qui ajoute `format: json` à `web_research` fait échouer
        l'étape en SKILL_VALIDATION. On garde uniquement les champs déclarés.
        """
        for step in plan.steps:
            skill = self.registry.get(step.skill)
            if skill is None or not isinstance(step.input, dict):
                continue
            schema = getattr(skill, "input_schema", None) or {}
            allowed = set((schema.get("properties") or {}).keys()) if isinstance(schema, dict) else set()
            if not allowed:
                continue
            dropped = [key for key in step.input if key not in allowed]
            for key in dropped:
                step.input.pop(key, None)
            if dropped:
                logger.info("Plan : champs ignorés pour %s : %s", step.skill, ", ".join(dropped))

    def _skills_digest(self) -> str:
        lines = []
        for manifest in self.registry.manifests():
            schema = manifest["input_schema"]
            props = ", ".join((schema.get("properties") or {}).keys())
            required = ", ".join(schema.get("required") or [])
            lines.append(
                f"- {manifest['name']} (risque {manifest['risk_level']}) : {manifest['description']}. "
                f"Champs: {props}. Requis: {required}."
            )
        return "\n".join(lines)

    # Forme imposée au modèle : sans schéma, un modèle « lite » renvoie un tableau
    # nu au lieu du plan attendu, et la mission retombe sur le plan minimal.
    PLAN_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "skill": {"type": "string"},
                        "title": {"type": "string"},
                        # Gemini n'émet que les propriétés déclarées : un `input`
                        # sans propriétés revient systématiquement vide.
                        "input": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "scope": {"type": "string"},
                                "depth": {"type": "string"},
                                "url": {"type": "string"},
                                "objective": {"type": "string"},
                                "context": {"type": "string"},
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                                "format": {"type": "string"},
                                "source_step": {"type": "string"},
                                "key": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                        "risk": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "skill", "title", "input"],
                },
            },
        },
        "required": ["goal", "steps"],
    }

    async def build_plan(self, goal: str, history: Sequence[dict[str, Any]] | None = None) -> Plan:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    skills=self._skills_digest(), max_steps=self.settings.max_task_steps
                ),
            }
        ]
        for item in list(history or [])[-6:]:
            messages.append({"role": item.get("role", "user"), "content": str(item.get("content", ""))[:2000]})
        messages.append({"role": "user", "content": goal[:4000]})

        last_error = ""
        for attempt in range(max(0, self.settings.max_plan_repair_attempts) + 1):
            try:
                result = await self.llm.chat(
                    messages,
                    json_mode=True,
                    purpose="plan",
                    max_tokens=2048,
                    timeout=min(30.0, self.settings.gemini_timeout_seconds),
                    schema=self.PLAN_SCHEMA,
                )
                plan = Plan.model_validate(result.json())
                _normalize_inputs(plan)
                self._drop_unknown_fields(plan)
                validated = validate_plan(plan, self.registry, max_steps=self.settings.max_task_steps)
                if validated.warnings:
                    logger.info("Plan accepté avec avertissements: %s", validated.warnings)
                return validated.plan
            except (LLMError, ValidationError, PlanValidationError) as exc:
                last_error = str(exc)[:300]
                logger.warning("Plan invalide (tentative %s): %s", attempt + 1, last_error)
                if attempt < self.settings.max_plan_repair_attempts:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Le plan précédent est invalide : "
                                f"{last_error}. Corrige et renvoie uniquement le JSON du plan."
                            ),
                        }
                    )

        logger.error("Plan non réparable, plan de repli minimal utilisé: %s", last_error)
        return self.fallback_plan(goal)

    def fallback_plan(self, goal: str) -> Plan:
        """Plan de repli sûr : une seule étape locale, réversible (R1)."""
        return Plan(
            goal=goal[:1000],
            steps=[
                PlanStep(
                    id="step_1",
                    skill="business_planning",
                    title="Structuration locale de la demande",
                    input={"objective": goal[:900]},
                    risk="R1",
                    depends_on=[],
                )
            ],
        )

    @staticmethod
    def plan_to_dict(plan: Plan) -> dict[str, Any]:
        return json.loads(plan.model_dump_json())

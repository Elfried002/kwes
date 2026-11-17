"""Registre des skills : manifeste YAML, schémas JSON, permissions, exécution isolée."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, field_validator

from app.agent.policy import SKILL_POLICIES
from app.core.config import Settings
from app.skills.base import (
    SkillContext,
    SkillError,
    SkillManifestError,
    SkillOutputError,
    SkillPermissionError,
    SkillResult,
    SkillTimeout,
    SkillValidationError,
)
from app.skills.normalize import normalize_payload

logger = logging.getLogger("kwes.skills")

# Droits maximaux qu'un skill peut déclarer (un manifeste ne peut pas élargir).
SKILL_PERMISSION_ALLOWLIST: dict[str, frozenset[str]] = {
    "web_research": frozenset({"web.search", "web.read"}),
    "business_planning": frozenset({"local.write"}),
    "browser_readonly": frozenset({"browser.read", "web.read"}),
    "remember": frozenset({"local.write"}),
    "document_write": frozenset({"local.write"}),
    "code_exec": frozenset({"local.write"}),
}


class NetworkSpec(BaseModel):
    mode: Literal["none", "allowlist", "open"] = "allowlist"
    domains: list[str] = Field(default_factory=list)


class ResourcesSpec(BaseModel):
    timeout_seconds: float = 60.0
    memory_mb: int = 512
    cpu_limit: float = 1.0


class ApprovalSpec(BaseModel):
    required_for: list[str] = Field(default_factory=list)


class SkillManifest(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=5, max_length=400)
    entrypoint: str = "skill.py"
    permissions: list[str] = Field(default_factory=list)
    risk_level: Literal["R0", "R1", "R2", "R3", "R4"] = "R0"
    network: NetworkSpec = Field(default_factory=NetworkSpec)
    resources: ResourcesSpec = Field(default_factory=ResourcesSpec)
    approval: ApprovalSpec = Field(default_factory=ApprovalSpec)

    @field_validator("permissions")
    @classmethod
    def _permissions_non_empty(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("permissions dupliquées")
        return value


@dataclass
class LoadedSkill:
    manifest: SkillManifest
    module: Any
    directory: Path
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    artifact_hash: str

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def timeout_seconds(self) -> float:
        return float(self.manifest.resources.timeout_seconds)


class SkillRegistry:
    def __init__(self, skills_dir: Path, settings: Settings) -> None:
        self.skills_dir = Path(skills_dir)
        self.settings = settings
        self._skills: dict[str, LoadedSkill] = {}
        self._load_errors: dict[str, str] = {}
        self._input_validators: dict[str, Draft202012Validator] = {}
        self._output_validators: dict[str, Draft202012Validator] = {}

    # -- Chargement --------------------------------------------------------
    def load(self) -> None:
        self._skills.clear()
        self._load_errors.clear()
        if not self.skills_dir.is_dir():
            logger.error("Dossier skills introuvable: %s", self.skills_dir)
            return
        for directory in sorted(self.skills_dir.iterdir()):
            if not directory.is_dir() or directory.name.startswith(("_", ".")):
                continue
            manifest_path = directory / "manifest.yaml"
            if not manifest_path.is_file():
                continue
            try:
                self._load_one(directory, manifest_path)
            except Exception as exc:
                self._load_errors[directory.name] = str(exc)
                logger.error("Skill %s non chargé: %s", directory.name, exc)
        logger.info("Skills chargés: %s", ", ".join(sorted(self._skills)) or "aucun")

    def _load_one(self, directory: Path, manifest_path: Path) -> None:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SkillManifestError("Manifeste YAML invalide.")
        manifest = SkillManifest.model_validate(raw)

        if manifest.name != directory.name:
            raise SkillManifestError("Le nom du manifeste doit correspondre au dossier.")

        policy = SKILL_POLICIES.get(manifest.name)
        if policy is None:
            raise SkillManifestError("Skill inconnu du policy engine.")
        if manifest.risk_level != policy.risk:
            # Empêche un manifeste de déclarer un risque plus faible que la politique.
            raise SkillManifestError(
                f"risk_level {manifest.risk_level} incohérent avec la politique {policy.risk}."
            )
        granted = SKILL_PERMISSION_ALLOWLIST.get(manifest.name, frozenset())
        extra = set(manifest.permissions) - set(granted)
        if extra:
            raise SkillManifestError(f"Permissions non autorisées: {sorted(extra)}")
        if not set(manifest.permissions) <= set(policy.permissions):
            raise SkillManifestError("Permissions hors politique du skill.")

        entry = directory / manifest.entrypoint
        if not entry.is_file() or entry.suffix != ".py":
            raise SkillManifestError("Point d'entrée introuvable.")

        input_schema = self._read_schema(directory / "schemas" / "input.json")
        output_schema = self._read_schema(directory / "schemas" / "output.json")
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator.check_schema(output_schema)

        module = self._import_module(manifest.name, entry)
        run = getattr(module, "run", None)
        if run is None or not inspect.iscoroutinefunction(run):
            raise SkillManifestError("Le skill doit exposer `async def run(payload, ctx)`.")

        artifact_hash = hashlib.sha256()
        for path in sorted(
            [manifest_path, entry, directory / "schemas" / "input.json", directory / "schemas" / "output.json"]
        ):
            artifact_hash.update(path.read_bytes())

        loaded = LoadedSkill(
            manifest=manifest,
            module=module,
            directory=directory,
            input_schema=input_schema,
            output_schema=output_schema,
            artifact_hash=artifact_hash.hexdigest(),
        )
        self._skills[manifest.name] = loaded
        self._input_validators[manifest.name] = Draft202012Validator(input_schema)
        self._output_validators[manifest.name] = Draft202012Validator(output_schema)

    @staticmethod
    def _read_schema(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise SkillManifestError(f"Schéma manquant: {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SkillManifestError(f"Schéma invalide: {path.name}")
        return payload

    @staticmethod
    def _import_module(name: str, entry: Path) -> Any:
        spec = importlib.util.spec_from_file_location(f"kwes_skill_{name}", entry)
        if spec is None or spec.loader is None:
            raise SkillManifestError("Import du skill impossible.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    # -- Accès -------------------------------------------------------------
    @property
    def names(self) -> list[str]:
        return sorted(self._skills)

    @property
    def load_errors(self) -> dict[str, str]:
        return dict(self._load_errors)

    def get(self, name: str) -> LoadedSkill | None:
        return self._skills.get(name)

    def manifests(self) -> list[dict[str, Any]]:
        out = []
        for skill in self._skills.values():
            out.append(
                {
                    "name": skill.name,
                    "description": skill.manifest.description,
                    "version": skill.manifest.version,
                    "risk_level": skill.manifest.risk_level,
                    "permissions": list(skill.manifest.permissions),
                    "input_schema": skill.input_schema,
                    "output_schema": skill.output_schema,
                    "artifact_hash": skill.artifact_hash,
                }
            )
        return out

    # -- Exécution ----------------------------------------------------------
    def validate_input(self, name: str, payload: dict[str, Any]) -> None:
        skill = self._skills.get(name)
        if skill is None:
            raise SkillValidationError(f"Skill inconnu: {name}")
        errors = sorted(self._input_validators[name].iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            raise SkillValidationError(
                "Entrée invalide pour le skill.",
                details={
                    "fields": [
                        {"path": ".".join(str(p) for p in err.path), "message": err.message}
                        for err in errors[:10]
                    ]
                },
            )

    def validate_output(self, name: str, output: dict[str, Any]) -> None:
        errors = sorted(self._output_validators[name].iter_errors(output), key=lambda e: list(e.path))
        if errors:
            raise SkillOutputError(
                "Sortie du skill non conforme au schéma.",
                details={
                    "fields": [
                        {"path": ".".join(str(p) for p in err.path), "message": err.message}
                        for err in errors[:10]
                    ]
                },
            )

    async def execute(
        self, name: str, payload: dict[str, Any], ctx: SkillContext
    ) -> SkillResult:
        skill = self._skills.get(name)
        if skill is None:
            raise SkillValidationError(f"Skill inconnu: {name}")

        # Synonymes connus (ex. « approfondie » → « deep ») avant validation.
        payload = normalize_payload(name, payload)
        self.validate_input(name, payload)

        missing = set(skill.manifest.permissions) - set(ctx.granted_permissions)
        if missing:
            raise SkillPermissionError(
                "Permissions manquantes pour exécuter le skill.",
                details={"missing": sorted(missing)},
            )

        timeout = min(skill.timeout_seconds, ctx.timeout_seconds or skill.timeout_seconds)
        try:
            result = await asyncio.wait_for(skill.module.run(payload, ctx), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise SkillTimeout(f"Le skill {name} a dépassé son délai de {timeout:.0f}s.") from exc
        except SkillError:
            raise
        except Exception as exc:
            ctx.logger.exception("Skill %s a échoué", name)
            raise SkillError("Échec interne du skill.") from exc

        if not isinstance(result, SkillResult):
            raise SkillOutputError("Le skill doit retourner un SkillResult.")
        self.validate_output(name, result.output)
        return result

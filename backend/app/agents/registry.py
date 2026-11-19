"""Registre d'agents KWES : chargement, validation, refus explicite.

Le registre est la seule porte d'entrée des agents dans le moteur. Il applique
trois règles :

1. **Fail closed** — un seul fichier invalide fait échouer le chargement complet ;
   aucun agent partiellement valide n'est disponible.
2. **Aucun outil non implémenté n'est exposé** — un outil au statut `declared`
   est conservé pour la traçabilité, jamais transmis au modèle.
3. **Aucun contournement d'isolation** — un agent dont l'exécution exigerait
   `DB_RLS_BYPASS` est refusé au chargement.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.agents.schema import AgentConfig

logger = logging.getLogger("kwes.agents.registry")


class AgentPackageError(RuntimeError):
    """Le package d'agents ne peut pas être chargé."""


class AgentNotFound(LookupError):
    """Aucun agent chargé ne porte cet identifiant."""


class LoadedAgent:
    """Agent validé et prêt à être proposé au répartiteur."""

    __slots__ = ("config", "path", "soul", "agent_md", "spec")

    def __init__(
        self,
        config: AgentConfig,
        path: Path,
        soul: Path,
        agent_md: Path,
        spec: Path,
    ) -> None:
        self.config = config
        self.path = path
        self.soul = soul
        self.agent_md = agent_md
        self.spec = spec

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def is_orchestrator(self) -> bool:
        return self.config.agent_type == "orchestrator"

    def executable_tools(self) -> list[str]:
        """Outils réellement exécutables : statut `implemented` uniquement."""
        status = self.config.capabilities.tool_status
        return sorted(
            tool for tool in self.config.capabilities.declared_tool_ids
            if status.get(tool) == "implemented"
        )

    def declared_only_tools(self) -> list[str]:
        status = self.config.capabilities.tool_status
        return sorted(
            tool for tool in self.config.capabilities.declared_tool_ids
            if status.get(tool) != "implemented"
        )

    def as_summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "type": self.config.agent_type,
            "version": self.config.version,
            "status": self.config.status,
            "executable_tools": len(self.executable_tools()),
            "declared_only_tools": len(self.declared_only_tools()),
            "timeout_seconds": self.config.execution.timeout_seconds,
            "max_tool_calls_per_task": self.config.execution.budget.max_tool_calls_per_task,
        }


class AgentRegistry:
    """Charge un package d'agents et expose des agents validés."""

    def __init__(self, package_root: Path) -> None:
        self.package_root = Path(package_root)
        self._agents: dict[str, LoadedAgent] = {}
        self.errors: list[str] = []

    # -- Chargement ------------------------------------------------------
    def load(self) -> "AgentRegistry":
        registry_path = self.package_root / "registry/agents.yaml"
        if not registry_path.exists():
            raise AgentPackageError(f"Registre introuvable : {registry_path}")

        registre = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        entries = list(registre.get("agents") or [])
        core_entry = registre.get("core")
        if core_entry:
            entries.insert(0, core_entry if isinstance(core_entry, dict) else {})

        if not entries:
            raise AgentPackageError("Registre vide : aucun agent à charger.")

        for entry in entries:
            self._load_one(entry)

        if self.errors:
            detail = "\n".join(f"  - {message}" for message in self.errors)
            raise AgentPackageError(
                f"{len(self.errors)} agent(s) refusé(s), chargement annulé :\n{detail}"
            )

        logger.info("Registre d'agents chargé : %s agent(s).", len(self._agents))
        return self

    def _load_one(self, entry: dict) -> None:
        config_rel = entry.get("config")
        if not config_rel:
            self.errors.append(f"Entrée sans chemin de configuration : {entry}")
            return
        config_path = self.package_root / config_rel
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            config = AgentConfig.model_validate(raw)
        except FileNotFoundError:
            self.errors.append(f"{config_rel} : fichier introuvable")
            return
        except Exception as exc:  # noqa: BLE001 — remonté agrégé
            self.errors.append(f"{config_rel} : {exc}")
            return

        if config.status == "retired":
            logger.info("Agent %s ignoré (retiré).", config.agent_id)
            return

        if config.agent_id in self._agents:
            self.errors.append(f"{config.agent_id} déclaré deux fois")
            return

        self._agents[config.agent_id] = LoadedAgent(
            config=config,
            path=config_path,
            soul=self.package_root / (entry.get("soul") or ""),
            agent_md=self.package_root / (entry.get("agent") or ""),
            spec=self.package_root / (entry.get("spec") or ""),
        )

    # -- Accès -----------------------------------------------------------
    def get(self, agent_id: str) -> LoadedAgent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFound(agent_id) from exc

    def get_orchestrator(self) -> LoadedAgent:
        for agent in self._agents.values():
            if agent.is_orchestrator:
                return agent
        raise AgentPackageError("Aucun orchestrateur dans le registre.")

    def specialists(self) -> list[LoadedAgent]:
        return [a for a in self._agents.values() if not a.is_orchestrator]

    def all(self) -> list[LoadedAgent]:
        return list(self._agents.values())

    def summary(self) -> dict:
        return {
            "total": len(self._agents),
            "orchestrators": sum(1 for a in self._agents.values() if a.is_orchestrator),
            "specialists": len(self.specialists()),
            "agents": [a.as_summary() for a in self._agents.values()],
        }

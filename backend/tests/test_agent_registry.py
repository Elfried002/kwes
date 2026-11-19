"""Tests du registre d'agents KWES (chargement, refus, contrats)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
import yaml

from app.agents import AgentRegistry
from app.agents.contracts import AgentResult, AgentTask, Evidence
from app.agents.registry import AgentPackageError

PACKAGE = Path(__file__).resolve().parents[2] / "docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1"


@pytest.fixture()
def package(tmp_path: Path) -> Path:
    """Copie du package réel, modifiable par les tests de refus."""
    if not PACKAGE.exists():
        pytest.skip("package agentique absent du dépôt")
    destination = tmp_path / "agents_pkg"
    shutil.copytree(PACKAGE, destination)
    return destination


def _config(package: Path, slug: str) -> Path:
    return package / "agents" / slug / "config.yaml"


def _patch(path: Path, **changes) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------- chargement
def test_package_se_charge(package: Path) -> None:
    registry = AgentRegistry(package).load()

    assert len(registry.all()) == 17
    assert len(registry.specialists()) == 16
    assert registry.get_orchestrator().agent_id == "kwes.core"
    assert all(agent.config.status == "defined_not_activated" for agent in registry.all())


def test_outils_declares_non_exposes(package: Path) -> None:
    registry = AgentRegistry(package).load()
    for agent in registry.all():
        exposes = set(agent.executable_tools())
        declares = set(agent.declared_only_tools())
        assert exposes.isdisjoint(declares)
        assert exposes | declares == set(agent.config.capabilities.declared_tool_ids)


def test_matrice_couvre_tous_les_outils(package: Path) -> None:
    registry = AgentRegistry(package).load()
    for agent in registry.specialists():
        outils = set(agent.config.capabilities.declared_tool_ids)
        assert outils == set(agent.config.approval_matrix), agent.agent_id


# ---------------------------------------------------------------- refus
def test_refuse_un_modele_hors_perimetre(package: Path) -> None:
    path = _config(package, "research")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # En V3, `model_policy` est hérité de defaults.yaml : on le redéclare pour
    # vérifier que le chargeur refuse un modèle hors périmètre.
    data["model_policy"] = {
        "allowed_models": ["gpt-4o"],
        "default_model": "gpt-4o",
        "allow_unlisted_models": False,
        "automatic_provider_fallback": False,
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="research"):
        AgentRegistry(package).load()


def test_refuse_un_specialiste_qui_distribue(package: Path) -> None:
    path = _config(package, "sales")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["authority"]["may_dispatch_agents"] = True
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="distribuer"):
        AgentRegistry(package).load()


def test_refuse_un_core_qui_modifie_les_permissions(package: Path) -> None:
    path = package / "core/config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["authority"]["may_change_user_permissions"] = True
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="permissions"):
        AgentRegistry(package).load()


def test_refuse_un_outil_sans_niveau(package: Path) -> None:
    path = _config(package, "finance")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["approval_matrix"].pop("transaction.prepare")
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="transaction.prepare"):
        AgentRegistry(package).load()


def test_refuse_un_outil_sans_statut(package: Path) -> None:
    path = _config(package, "tech")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["capabilities"]["tool_status"].pop("code.read")
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="code.read"):
        AgentRegistry(package).load()


def test_refuse_le_contournement_de_la_rls(package: Path) -> None:
    path = _config(package, "documents")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["execution"]["isolation"]["bypass_rls_forbidden"] = False
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="RLS"):
        AgentRegistry(package).load()


def test_refuse_un_delai_hors_bornes(package: Path) -> None:
    path = _config(package, "vision")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["execution"]["timeout_seconds"] = 5000
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(AgentPackageError, match="vision"):
        AgentRegistry(package).load()


# ---------------------------------------------------------------- contrats
def test_contrat_de_tache_impose_kwes() -> None:
    with pytest.raises(ValueError):
        AgentTask(mission_id=uuid.uuid4(), agent_id="research", objective="x", expected_output="y")


def test_resultat_complete_sans_preuve_nest_pas_verifie() -> None:
    task = AgentTask(
        mission_id=uuid.uuid4(),
        agent_id="kwes.research",
        objective="Chercher le prix du cacao",
        expected_output="Prix daté et sourcé",
    )
    result = AgentResult(
        task_id=task.task_id,
        mission_id=task.mission_id,
        agent_id=task.agent_id,
        status="completed",
        summary="Prix trouvé.",
    )
    assert result.is_verified() is False

    result.evidence.append(Evidence(kind="source", reference="https://example.org", detail="page officielle"))
    assert result.is_verified() is True

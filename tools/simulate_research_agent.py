"""Simulation de l'agent Research : chargement, permissions, plan à blanc.

Aucune exécution d'outil, aucun appel LLM : on vérifie que le registre accepte
l'agent, que ses outils exécutables sont bien ceux du moteur, et qu'un contrat
de tâche peut lui être adressé sans lui donner de privilège indu.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from app.agents import AgentRegistry
from app.agents.contracts import AgentTask, Evidence, AgentResult

PKG = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/kwes-staging/agents_pkg")

registry = AgentRegistry(PKG).load()
resume = registry.summary()
print("== registre ==")
print(f"agents: {resume['total']} (orchestrateurs: {resume['orchestrators']}, spécialistes: {resume['specialists']})")

agent = registry.get("kwes.research")
config = agent.config

print("\n== agent research ==")
print("type:", config.agent_type, "| version:", config.version, "| statut:", config.status)
print("autonomie:", config.autonomy.get("supported_levels"))
print("timeout:", config.execution.timeout_seconds, "s | tentatives:", config.execution.max_retries)
print("budget/tâche:", config.execution.budget.max_tool_calls_per_task, "appels")
print("isolation:", config.execution.isolation.model_dump())

executables = agent.executable_tools()
declares = agent.declared_only_tools()
print("\noutils exécutables:", executables)
print("outils déclarés (non exposés):", declares)

print("\n== matrice d'approbation ==")
for outil, regle in sorted(config.approval_matrix.items()):
    statut = "exécutable" if outil in executables else "déclaré"
    print(f"  {outil:<26} {regle.level:<3} {regle.approval:<15} ({statut})")

# Contrôle de sécurité : aucun outil déclaré ne doit être proposé à l'exécution
fuite = [outil for outil in declares if outil in executables]
print("\noutil déclaré exposé par erreur:", fuite or "aucun")

# Contrat de tâche à blanc
tache = AgentTask(
    mission_id=uuid.uuid4(),
    agent_id="kwes.research",
    objective="Établir le prix du cacao en Côte d'Ivoire avec deux sources datées.",
    expected_output="Note de 5 lignes, prix daté, deux sources indépendantes.",
    allowed_tools=[outil for outil in executables],
    autonomy_level="A1",
    deadline_seconds=config.execution.timeout_seconds,
    max_tool_calls=config.execution.budget.max_tool_calls_per_task,
    acceptance_criteria=[
        "prix daté et sourcé",
        "deux sources indépendantes",
        "aucune donnée inventée",
    ],
    language="fr",
)
print("\n== contrat de tâche (à blanc) ==")
print(json.dumps(json.loads(tache.model_dump_json()), ensure_ascii=False, indent=2)[:700])

# Résultat attendu : un livrable sans preuve n'est pas vérifié
resultat = AgentResult(
    task_id=tache.task_id,
    mission_id=tache.mission_id,
    agent_id=tache.agent_id,
    status="completed",
    summary="Prix relevé.",
)
print("\nrésultat sans preuve vérifié ?", resultat.is_verified())
resultat.evidence.append(Evidence(kind="source", reference="https://example.org", detail="communiqué officiel"))
print("résultat avec preuve vérifié ?", resultat.is_verified())

print("\n== verdict simulation ==")
bloquants = []
if fuite:
    bloquants.append("outil déclaré exposé")
if not executables:
    bloquants.append("aucun outil exécutable")
if config.execution.isolation.bypass_rls_forbidden is not True:
    bloquants.append("isolation non exigée")
print("prêt pour un pilote en staging:", not bloquants, bloquants or "")

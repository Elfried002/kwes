"""Agents KWES : registre, schémas et contrats d'échange.

Ce paquet ne contient **aucune** logique d'exécution : il valide et expose des
définitions d'agents. Le répartiteur (à construire) consomme `AgentRegistry` et
`contracts.AgentTask` / `contracts.AgentResult`.
"""

from app.agents.contracts import AgentResult, AgentTask, Evidence
from app.agents.registry import (
    AgentNotFound,
    AgentPackageError,
    AgentRegistry,
    LoadedAgent,
)
from app.agents.schema import AgentConfig

__all__ = [
    "AgentConfig",
    "AgentNotFound",
    "AgentPackageError",
    "AgentRegistry",
    "AgentResult",
    "AgentTask",
    "Evidence",
    "LoadedAgent",
]

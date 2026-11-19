"""Vérifie les 16 AGENT.md réécrits : structure, langue, différenciation."""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import yaml

PKG = Path("/home/babayaga/business/kwes/docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1")
SECTIONS = [
    "## Méthode du domaine",
    "## Sources et outils autorisés",
    "## Critères de qualité vérifiables",
    "## Modes d'échec et escalade",
    "## Démarrage d'une tâche",
    "## Exécution",
    "## Contrôles",
    "## Règles communes non négociables",
]


def shingles(text: str, size: int = 6) -> set[str]:
    words = re.findall(r"[a-zà-ÿ0-9']+", text.lower())
    return {" ".join(words[i : i + size]) for i in range(max(0, len(words) - size + 1))}


def hors_tronc(texte: str) -> str:
    return texte.split("## Règles communes")[0]


lignes_par_agent: dict[str, int] = {}
problemes: list[str] = []

for dossier in sorted((PKG / "agents").iterdir()):
    if not dossier.is_dir():
        continue
    slug = dossier.name
    fichier = dossier / "AGENT.md"
    # Les titres du package utilisent l'apostrophe typographique : on normalise
    # avant de comparer, sinon la vérification échoue sur un détail de glyphe.
    texte = fichier.read_text(encoding="utf-8").replace("\u2019", "'")
    lignes_par_agent[slug] = len(texte.splitlines())

    manquantes = [s for s in SECTIONS if s not in texte]
    if manquantes:
        problemes.append(f"{slug}: sections manquantes {manquantes}")

    if "langue de la dernière réplique" not in texte:
        problemes.append(f"{slug}: règle de langue absente")

    if not (55 <= lignes_par_agent[slug] <= 95):
        problemes.append(f"{slug}: {lignes_par_agent[slug]} lignes (attendu 55-95)")

    # Outils cités dans la procédure mais non déclarés dans la config
    config = yaml.safe_load((dossier / "config.yaml").read_text(encoding="utf-8"))
    declares = set(data for data in (config.get("capabilities") or {}).get("declared_tool_ids") or [])
    cites = set(re.findall(r"\b([a-z_]+\.[a-z_.]+)\b", texte))
    inconnus = sorted(c for c in cites if c not in declares)
    if inconnus:
        problemes.append(f"{slug}: outils cités hors config -> {inconnus}")

# Similarité hors tronc commun
textes = {p.name: hors_tronc((PKG / "agents" / p.name / "AGENT.md").read_text(encoding="utf-8"))
          for p in sorted((PKG / "agents").iterdir()) if p.is_dir()}
paires = []
for a, b in itertools.combinations(sorted(textes), 2):
    sa, sb = shingles(textes[a]), shingles(textes[b])
    if sa and sb:
        paires.append((len(sa & sb) / len(sa | sb), a, b))
paires.sort(reverse=True)

print(f"agents vérifiés : {len(lignes_par_agent)}")
print(f"lignes : min {min(lignes_par_agent.values())}, max {max(lignes_par_agent.values())}")
print(f"similarité hors tronc : max {paires[0][0]:.0%} ({paires[0][1]}/{paires[0][2]}), "
      f"médiane {paires[len(paires)//2][0]:.0%}")
print(f"problèmes : {len(problemes)}")
for p in problemes[:12]:
    print("  -", p)

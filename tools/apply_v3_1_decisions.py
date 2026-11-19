"""Applique les décisions du 19/11/2026 au package V3_1.

Décisions appliquées ici (mécaniques, donc scriptables) :
- Core ne peut pas modifier les permissions utilisateur (`may_change_user_permissions: false`) ;
- politique linguistique commune ajoutée à KWES Core et aux 16 spécialistes ;
- table de correspondance A0–A4 ↔ R1–R4 publiée dans shared/config/ ;
- isolation d'exécution déclarée par agent : rôle applicatif, contexte par tâche,
  interdiction de DB_RLS_BYPASS pour les agents ;
- budget : structure alignée sur les quotas existants, valeurs à valider par le propriétaire.

Les identités de domaine (mission, caractère, périmètre) ne sont pas modifiées :
la politique linguistique est ajoutée comme section distincte.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PKG = Path("/home/babayaga/business/kwes/docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1")

LANGUE = """## Langue

- Tu réponds dans la langue de la dernière réplique de l'utilisateur : français ou anglais.
- Le français est la langue par défaut ; toute autre langue reçue donne une réponse en français.
- Tu ne mélanges jamais deux langues dans une même réponse, pas même un mot.
- Cette règle vaut aussi pour les missions déléguées, les livrables et les interactions vocales :
  la langue d'une mission est celle de l'utilisateur qui l'a demandée.

"""

MAPPING = {
    "mapping_version": "1.0.0",
    "principle": (
        "La correspondance ne peut jamais relever une action d'un niveau inférieur. "
        "En cas de doute, c'est le niveau le plus élevé des deux systèmes qui s'applique."
    ),
    "levels": [
        {
            "package": "A0",
            "label": "Consultation",
            "engine": ["R0", "R1"],
            "approval": "none",
            "examples": ["lire une page", "chercher sur le web", "analyser un document"],
            "rule": "Aucune action extérieure. Lecture seule autorisée par les permissions.",
        },
        {
            "package": "A1",
            "label": "Préparation",
            "engine": ["R1"],
            "approval": "none",
            "examples": ["rédiger un brouillon", "produire un plan", "créer un document interne"],
            "rule": "Effet interne uniquement. Rien ne sort du système sans passage en A3.",
        },
        {
            "package": "A2",
            "label": "Action réversible",
            "engine": ["R1", "R2"],
            "approval": "policy_checked",
            "examples": ["exécuter du code dans l'espace de travail", "lancer une suite de tests"],
            "rule": (
                "Réversible et confiné. Exige un contrôle de politique ; si l'outil est classé "
                "R2 côté moteur, l'approbation R2 s'applique."
            ),
        },
        {
            "package": "A3",
            "label": "Action externe",
            "engine": ["R2"],
            "approval": "explicit",
            "examples": ["envoyer un email", "publier", "exécuter un workflow externe", "scan autorisé"],
            "rule": (
                "Effet hors du système. Approbation explicite obligatoire, avec le contenu exact "
                "affiché. Une approbation ne vaut que pour l'action décrite (hash du payload)."
            ),
        },
        {
            "package": "A4",
            "label": "Action financière ou critique",
            "engine": ["R3", "R4"],
            "approval": "strong",
            "examples": ["paiement", "transfert", "suppression définitive", "changement d'accès critique"],
            "rule": (
                "Le moteur refuse R3 et R4 tant que KWES Pay et les validations renforcées ne sont "
                "pas activés. Aucune correspondance ne peut transformer A4 en R2."
            ),
        },
    ],
    "forbidden_downgrades": [
        "A3 → R1 (action externe traitée comme lecture)",
        "A4 → R2 (action financière traitée comme réversible)",
        "A2 → R0 (exécution de code traitée comme consultation)",
    ],
    "verification": (
        "Le chargeur d'agents doit refuser toute matrice d'approbation où un outil A3/A4 "
        "correspond à un niveau moteur inférieur à R2/R3."
    ),
}


def main() -> None:
    # 1. Politique de langue dans les 17 SOUL.md
    ajoutes = 0
    for soul in sorted(PKG.rglob("SOUL.md")):
        texte = soul.read_text(encoding="utf-8")
        if "## Langue" in texte:
            continue
        marqueur = "## Règles communes non négociables"
        if marqueur in texte:
            texte = texte.replace(marqueur, LANGUE + marqueur, 1)
        else:
            texte = texte.rstrip() + "\n\n" + LANGUE
        soul.write_text(texte, encoding="utf-8")
        ajoutes += 1

    # 2. Core : permission corrigée + isolation + budget
    core_path = PKG / "core/config.yaml"
    core = yaml.safe_load(core_path.read_text(encoding="utf-8"))
    core["authority"]["may_change_user_permissions"] = False
    core["authority"]["can_request_permission_change_through_user_approval"] = True
    core["execution"]["isolation"] = {
        "db_role": "kwes_app",
        "rls_context": "per_task",
        "bypass_rls_forbidden": True,
    }
    core["execution"]["budget"] = {
        "quota_source": "kwes_existing_quotas",
        "max_tool_calls_per_task": 12,
        "max_tool_calls_per_mission": 60,
        "max_wall_clock_seconds_per_task": 180,
        "max_wall_clock_seconds_per_mission": 900,
        "max_cost_eur_per_task": None,
        "max_cost_eur_per_mission": None,
        "status": "proposal_pending_owner_validation",
        "reference": "docs/integration/KWES_BUDGET_PROPOSAL.md",
    }
    core_path.write_text(yaml.safe_dump(core, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # 3. Spécialistes : isolation et budget alignés
    modifies = 0
    for path in sorted((PKG / "agents").glob("*/config.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        execution = data.setdefault("execution", {})
        execution["isolation"] = {
            "db_role": "kwes_app",
            "rls_context": "per_task",
            "bypass_rls_forbidden": True,
        }
        execution["budget"] = {
            "quota_source": "kwes_existing_quotas",
            "max_tool_calls_per_task": 12,
            "max_cost_eur_per_task": None,
            "status": "proposal_pending_owner_validation",
            "reference": "docs/integration/KWES_BUDGET_PROPOSAL.md",
        }
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        modifies += 1

    # 4. Table de correspondance publiée
    target = PKG / "shared/config/policy-mapping.yaml"
    target.write_text(yaml.safe_dump(MAPPING, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print("SOUL.md complétés :", ajoutes)
    print("configs spécialistes mis à jour :", modifies)
    print("mapping écrit :", target.relative_to(PKG))
    print("core may_change_user_permissions :", core["authority"]["may_change_user_permissions"])


if __name__ == "__main__":
    main()

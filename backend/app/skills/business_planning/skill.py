"""Skill business_planning — plan d'action local, déterministe, sans action externe.

Aucun appel réseau. Le résultat est reproductible pour une même entrée
(contrat de test « résultat reproductible lorsque possible »).
"""

from __future__ import annotations

import re
from typing import Any

from app.skills.base import SkillContext, SkillResult


def _theme(objective: str) -> str:
    cleaned = re.sub(r"\s+", " ", objective).strip().rstrip(".!?")
    if len(cleaned) <= 90:
        return cleaned
    cut = cleaned[:90]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut) + "…"


def _phases(theme: str, constraints: list[str]) -> list[dict[str, Any]]:
    constraint_note = (
        f" Contraintes à respecter : {'; '.join(constraints[:4])}." if constraints else ""
    )
    definitions = [
        ("step_1", "Cadrage", f"Définir le résultat attendu pour « {theme} », les critères de succès et le périmètre exclu."),
        ("step_2", "Analyse", f"Rassembler les faits vérifiables sur « {theme} » et identifier les hypothèses à tester."),
        ("step_3", "Plan d'action", f"Séquencer les actions concrètes pour « {theme} » avec responsables et échéances."),
        ("step_4", "Ressources", "Estimer les ressources nécessaires (temps, budget indicatif, compétences) et les dépendances."),
        ("step_5", "Mesure", "Définir les indicateurs de suivi, la fréquence de revue et le déclencheur de révision."),
    ]
    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for index, (step_id, title, description) in enumerate(definitions):
        described = description + (constraint_note if index == 0 else "")
        steps.append(
            {
                "id": step_id,
                "title": title,
                "description": described,
                "depends_on": [previous] if previous else [],
            }
        )
        previous = step_id
    return steps


def _risks(constraints: list[str]) -> list[dict[str, str]]:
    base = [
        {
            "risk": "Périmètre trop large",
            "impact": "Dispersion des efforts et livrable incomplet",
            "mitigation": "Cadrer un objectif mesurable et découper en livrables courts",
        },
        {
            "risk": "Données insuffisantes ou non fiables",
            "impact": "Décisions fondées sur des hypothèses non vérifiées",
            "mitigation": "Séparer faits sourcés et hypothèses, vérifier avant engagement",
        },
        {
            "risk": "Dépendance à un fournisseur externe",
            "impact": "Retard ou blocage si le service est indisponible",
            "mitigation": "Prévoir un mode dégradé et une solution de repli documentée",
        },
    ]
    for constraint in constraints[:3]:
        base.append(
            {
                "risk": f"Contrainte: {constraint[:120]}",
                "impact": "Réduction des options d'exécution",
                "mitigation": "Intégrer la contrainte dès le cadrage et valider avec le décideur",
            }
        )
    return base


def _kpis(theme: str) -> list[dict[str, str]]:
    return [
        {"name": "Avancement du plan", "metric": "% d'étapes terminées", "target": "100 % en fin de cycle"},
        {"name": "Qualité des sources", "metric": "Part de faits sourcés", "target": "≥ 80 %"},
        {"name": f"Adoption — {theme[:40]}", "metric": "Utilisateurs actifs ou tâches réalisées", "target": "À fixer avec le décideur"},
    ]


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    objective = str(payload["objective"]).strip()
    raw_constraints = payload.get("constraints") or []
    if isinstance(raw_constraints, str):
        # Tolérance documentée : le planner peut renvoyer une phrase unique.
        raw_constraints = [c for c in re.split(r"[;,]", raw_constraints)]
    constraints = [str(c).strip() for c in raw_constraints if str(c).strip()][:12]
    context = payload.get("context")
    publish_external = bool(payload.get("publish_external"))

    theme = _theme(objective)
    steps = _phases(theme, constraints)
    risks = _risks(constraints)
    kpis = _kpis(theme)

    assumptions = [
        "Le décideur valide le périmètre avant l'engagement de ressources.",
        "Les données externes utilisées seront vérifiées avant toute décision.",
    ]
    if context:
        assumptions.append(f"Contexte fourni pris en compte : {str(context)[:180]}")
    if constraints:
        assumptions.append("Les contraintes déclarées sont traitées comme fermes.")

    summary = (
        f"Plan en {len(steps)} étapes pour « {theme} », préparé localement. "
        f"{len(risks)} risque(s) identifié(s), {len(kpis)} indicateur(s) de suivi."
    )
    external_action = {
        "requested": publish_external,
        "performed": False,
        "reason": (
            "Aucune intégration de publication externe n'est active dans l'Alpha : "
            "le livrable reste local et n'est pas publié."
            if publish_external
            else "Aucune action externe demandée."
        ),
    }
    if publish_external:
        summary += " Publication externe NON effectuée (aucune intégration active)."

    ctx.logger.info("business_planning objective=%r steps=%s", theme[:60], len(steps))
    return SkillResult(
        output={
            "summary": summary,
            "steps": steps,
            "risks": risks,
            "kpis": kpis,
            "assumptions": assumptions,
            "external_action": external_action,
        },
        summary=summary,
        evidence=[{"type": "plan", "steps": [s["id"] for s in steps]}],
    )

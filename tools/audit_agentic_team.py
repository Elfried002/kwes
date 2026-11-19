"""Audit statique du package agentique KWES (Core + agents spécialisés).

Le script ne modifie rien : il inventorie, valide et croise les fichiers, puis
produit un JSON de constats que les rapports reprennent tels quels.

Usage :
    backend/.venv/bin/python tools/audit_agentic_team.py <dossier_du_package>
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REQUIRED_FILES = ("SOUL.md", "AGENT.md", "AGENT_SPEC.md", "config.yaml")
ALLOWED_MODELS = {"gemini-3.8-live", "gemini-3.8-live-extended-thinking"}
# Skills réellement présents dans le dépôt KWES aujourd'hui.
# Correspondance entre le vocabulaire du package et les skills réellement installés.
TOOL_TO_SKILL = {
    "web.search": "web_research",
    "research.synthesis": "web_research",
    "source.citation": "web_research",
    "local.info.research": "web_research",
    "service.compare": "web_research",
    "lead.research": "web_research",
    "web.page.read": "browser_readonly",
    "code.read": "code_exec",
    "code.write.workspace": "code_exec",
    "test.run.sandbox": "code_exec",
    "document.create": "document_write",
    "profile.preference.read": "remember",
    "business.planning": "business_planning",
}

REAL_SKILLS = {
    "web_research",
    "browser_readonly",
    "code_exec",
    "document_write",
    "remember",
    "business_planning",
}
SECRET_PATTERNS = {
    "clé Gemini/Google": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "clé OpenAI": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "jeton JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    "clé Supabase": re.compile(r"sb_(publishable|secret)_[A-Za-z0-9_-]{20,}"),
    "mot de passe en clair": re.compile(r"(?i)(password|passwd|secret|api_key)\s*[:=]\s*[\"']?[A-Za-z0-9!@#$%^&*_-]{8,}"),
}
AUTONOMY = {"A0", "A1", "A2", "A3", "A4"}

findings: list[dict] = []


def add(niveau: str, controle: str, fichier: str, probleme: str, risque: str, correction: str) -> None:
    findings.append(
        {
            "niveau": niveau,
            "controle": controle,
            "fichier": fichier,
            "probleme": probleme,
            "risque": risque,
            "correction": correction,
        }
    )


def shingles(text: str, size: int = 5) -> set[str]:
    words = re.findall(r"[a-zà-ÿ0-9']+", text.lower())
    return {" ".join(words[i : i + size]) for i in range(max(0, len(words) - size + 1))}


def main(root: Path) -> int:
    if not root.is_dir():
        print(f"Dossier introuvable : {root}")
        return 2

    # ---------- 1. Inventaire ----------
    agent_dirs = sorted(
        {
            path.parent
            for name in REQUIRED_FILES
            for path in root.rglob(name)
        }
    )
    configs = sorted(root.rglob("config.yaml"))
    souls = sorted(root.rglob("SOUL.md"))
    agents_md = sorted(root.rglob("AGENT.md"))
    specs = sorted(root.rglob("AGENT_SPEC.md"))

    inventaire = {
        "dossier": str(root),
        "agents_detectes": len(agent_dirs),
        "fichiers": {
            "SOUL.md": len(souls),
            "AGENT.md": len(agents_md),
            "AGENT_SPEC.md": len(specs),
            "config.yaml": len(configs),
        },
        "total_fichiers": sum(1 for _ in root.rglob("*") if _.is_file()),
        "taille_octets": sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
    }

    if len(souls) != len(agents_md) or len(souls) != len(specs) or len(souls) != len(configs):
        add(
            "CRITIQUE",
            "Structure",
            "package",
            f"Nombre de fichiers incohérent : SOUL={len(souls)}, AGENT={len(agents_md)}, "
            f"SPEC={len(specs)}, config={len(configs)}",
            "Agents incomplets : un rôle sans identité ou sans configuration ne peut pas être instancié.",
            "Compléter chaque agent pour qu'il ait exactement les quatre fichiers.",
        )

    for directory in agent_dirs:
        manquants = [name for name in REQUIRED_FILES if not (directory / name).exists()]
        if manquants:
            add(
                "CRITIQUE",
                "Structure",
                str(directory.relative_to(root)),
                f"Fichiers manquants : {', '.join(manquants)}",
                "Agent inexploitable par le moteur.",
                "Ajouter les fichiers manquants ou retirer l'agent du registre.",
            )
        for name in REQUIRED_FILES:
            path = directory / name
            if path.exists() and path.stat().st_size < 80:
                add(
                    "ÉLEVÉ",
                    "Structure",
                    str(path.relative_to(root)),
                    f"Fichier quasi vide ({path.stat().st_size} octets).",
                    "Identité ou configuration factice, non exécutable.",
                    "Rédiger le contenu réel ou retirer l'agent.",
                )

    # ---------- 2. Configurations YAML ----------
    configs_data: dict[str, dict] = {}
    for path in configs:
        rel = str(path.relative_to(root))
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            add("CRITIQUE", "YAML", rel, f"Syntaxe invalide : {exc}", "Le moteur ne peut pas charger l'agent.", "Corriger la syntaxe YAML.")
            continue
        if not isinstance(data, dict):
            add("CRITIQUE", "YAML", rel, "Racine YAML qui n'est pas un objet.", "Configuration illisible.", "Utiliser une mapping racine.")
            continue
        configs_data[rel] = data

        model = str(data.get("model") or data.get("models", {}).get("primary", "") if isinstance(data.get("models"), dict) else data.get("model") or "")
        if model and model not in ALLOWED_MODELS:
            add(
                "CRITIQUE",
                "Modèles",
                rel,
                f"Modèle déclaré « {model} » hors périmètre autorisé.",
                "Rupture du contrat : seuls gemini-3.8-live et gemini-3.8-live-extended-thinking sont autorisés.",
                f"Remplacer par l'un des modèles autorisés : {sorted(ALLOWED_MODELS)}.",
            )

        raw_autonomy = data.get("autonomy") or data.get("autonomy_level") or ""
        if isinstance(raw_autonomy, dict):
            niveaux = raw_autonomy.get("supported_levels") or list((raw_autonomy.get("levels") or {}).keys())
            inconnus_auto = [n for n in niveaux if n not in AUTONOMY]
            niveau = ",".join(niveaux)
        else:
            inconnus_auto = [raw_autonomy] if raw_autonomy and raw_autonomy not in AUTONOMY else []
            niveau = str(raw_autonomy)
        if inconnus_auto:
            add("ÉLEVÉ", "Autonomie", rel, f"Niveaux d'autonomie inconnus : {inconnus_auto}", "Politique d'approbation indéterminée.", "Utiliser A0 à A4.")

        caps = data.get("capabilities") or {}
        tools = (
            caps.get("declared_tool_ids")
            or data.get("tools")
            or data.get("skills")
            or []
        )
        statuts = caps.get("tool_status") or {}
        if isinstance(tools, list):
            # Un outil étiqueté `declared` est assumé comme non implémenté : ce
            # n'est plus une fausse capacité, c'est une feuille de route.
            def couvert(t: str) -> bool:
                return TOOL_TO_SKILL.get(t) in REAL_SKILLS or t in REAL_SKILLS

            annonces = [
                t for t in tools
                if isinstance(t, str) and not couvert(t) and statuts.get(t) != "declared"
            ]
            if annonces:
                add(
                    "ÉLEVÉ",
                    "Compatibilité",
                    rel,
                    f"Outils présentés comme disponibles mais absents du moteur : {', '.join(sorted(set(annonces)))}",
                    "L'agent annoncera une capacité qu'il ne peut pas exécuter (fausse capacité).",
                    "Marquer l'outil `declared` dans tool_status, ou implémenter le skill.",
                )
            declares = [t for t in tools if statuts.get(t) == "declared"]
            if declares:
                add(
                    "MOYEN",
                    "Compatibilité",
                    rel,
                    f"{len(declares)} outil(s) déclaré(s) sans implémentation, correctement étiquetés : "
                    f"{', '.join(sorted(declares)[:6])}{'…' if len(declares) > 6 else ''}",
                    "Feuille de route à tenir ; aucun risque tant que le moteur refuse les outils non enregistrés.",
                    "Ne jamais exposer un outil `declared` au modèle, et suivre l'avancement dans le registre.",
                )

    # ---------- 3. Doublons d'identité ----------
    textes = {str(p.relative_to(root)): p.read_text(encoding="utf-8", errors="replace") for p in souls + agents_md}
    signature: dict[str, set[str]] = {}
    for rel, texte in textes.items():
        if len(texte) > 200:
            signature[rel] = shingles(texte)

    cles = sorted(signature)
    # Une anomalie par agent (et non par paire) : on retient son voisin le plus proche.
    plus_proche: dict[str, tuple[float, str]] = {}
    for left in cles:
        for right in cles:
            if left == right:
                continue
            a, b = signature[left], signature[right]
            if not a or not b:
                continue
            score = len(a & b) / len(a | b)
            if score > plus_proche.get(left, (0.0, ""))[0]:
                plus_proche[left] = (score, right)
    for fichier, (score, voisin) in sorted(plus_proche.items()):
        if score > 0.60 and fichier.endswith("AGENT.md"):
            add(
                "ÉLEVÉ",
                "Identités",
                fichier,
                f"Contenu similaire à {score:.0%} avec {voisin}.",
                "Procédures quasi identiques : la spécialisation n'existe que dans le vocabulaire.",
                "Rédiger des sections propres au métier (méthode, sources, critères, échecs).",
            )
        elif score > 0.75:
            add(
                "MOYEN",
                "Identités",
                fichier,
                f"Contenu similaire à {score:.0%} avec {voisin}.",
                "Risque de confusion de rôle sur les parties communes.",
                "Vérifier que la partie spécifique suffit à distinguer l'agent.",
            )

    # ---------- 4. Orchestration : graphe de délégation ----------
    noms = {}
    for rel, data in configs_data.items():
        nom = str(
            data.get("agent_id")
            or (data.get("agent") or {}).get("agent_id")
            or data.get("display_name")
            or ""
        ).strip()
        if not nom:
            add("ÉLEVÉ", "Registre", rel, "Aucun nom d'agent déclaré.", "Registre impossible à construire.", "Ajouter une clé name.")
        elif nom in noms:
            add("CRITIQUE", "Registre", rel, f"Nom d'agent en double : {nom} (déjà déclaré dans {noms[nom]}).", "Collision de registre.", "Renommer l'un des deux.")
        else:
            noms[nom] = rel

    cibles = defaultdict(list)
    for rel, data in configs_data.items():
        nom = str(data.get("name") or "")
        delegation = data.get("delegation") or data.get("delegates_to") or []
        if isinstance(delegation, dict):
            delegation = delegation.get("agents") or delegation.get("targets") or []
        if isinstance(delegation, str):
            delegation = [delegation]
        for cible in delegation or []:
            if isinstance(cible, dict):
                cible = cible.get("agent") or cible.get("name") or ""
            if cible and cible not in noms:
                add(
                    "ÉLEVÉ",
                    "Orchestration",
                    rel,
                    f"Délégation vers un agent inexistant : {cible}",
                    "Échec à l'exécution, mission bloquée.",
                    "Corriger la cible ou créer l'agent manquant.",
                )
            elif cible:
                cibles[nom].append(cible)

    # Cycles simples (A → B → A)
    for source, listes in cibles.items():
        for cible in listes:
            if source in cibles.get(cible, []):
                add(
                    "ÉLEVÉ",
                    "Orchestration",
                    source,
                    f"Boucle de délégation entre {source} et {cible}.",
                    "Risque d'appels récursifs et de blocage.",
                    "Rendre la délégation strictement descendante (Core → spécialiste).",
                )

    # ---------- 5. Sécurité : secrets et autonomie ----------
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml", ".md", ".json", ".env", ".txt"}:
            continue
        contenu = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(contenu):
                add(
                    "CRITIQUE",
                    "Secrets",
                    str(path.relative_to(root)),
                    f"Motif de secret détecté ({label}).",
                    "Fuite de credentials si le package est partagé ou versionné.",
                    "Retirer la valeur, la remplacer par une référence à un coffre.",
                )
                break

    for rel, data in configs_data.items():
        niveau = str(data.get("autonomy") or data.get("autonomy_level") or "")
        permissions = data.get("permissions") or data.get("allowed_actions") or []
        if niveau in {"A3", "A4"} and data.get("requires_approval") is False:
            add(
                "CRITIQUE",
                "Sécurité",
                rel,
                f"Autonomie {niveau} sans approbation obligatoire.",
                "Action externe ou financière exécutable sans validation humaine.",
                "Imposer requires_approval: true pour A3 et A4.",
            )
        if isinstance(permissions, list):
            dangereuses = [p for p in permissions if isinstance(p, str) and re.search(r"(pay|transfer|delete|admin|secret|sudo)", p, re.I)]
            if dangereuses and niveau in {"A0", "A1"}:
                add(
                    "ÉLEVÉ",
                    "Sécurité",
                    rel,
                    f"Permissions sensibles ({', '.join(dangereuses)}) avec autonomie {niveau}.",
                    "Élévation de privilèges implicite.",
                    "Aligner les permissions sur le niveau d'autonomie déclaré.",
                )

    # ---------- 6. Synthèse ----------
    compteur = Counter(f["niveau"] for f in findings)
    resultat = {
        "inventaire": inventaire,
        "agents": {nom: rel for nom, rel in sorted(noms.items())},
        "constats": findings,
        "synthese": {
            "CRITIQUE": compteur.get("CRITIQUE", 0),
            "ÉLEVÉ": compteur.get("ÉLEVÉ", 0),
            "MOYEN": compteur.get("MOYEN", 0),
            "FAIBLE": compteur.get("FAIBLE", 0),
            "total": len(findings),
        },
        "empreinte_package": hashlib.sha256(
            "".join(sorted(p.name + str(p.stat().st_size) for p in root.rglob("*") if p.is_file())).encode()
        ).hexdigest()[:16],
    }

    sortie = Path("/home/babayaga/business/kwes/docs/audit")
    sortie.mkdir(parents=True, exist_ok=True)
    fichier = sortie / "audit_agentic_team.json"
    fichier.write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(inventaire, ensure_ascii=False, indent=2))
    print("agents :", len(noms))
    print("synthèse :", resultat["synthese"])
    print("détail :", fichier)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]).expanduser().resolve()))

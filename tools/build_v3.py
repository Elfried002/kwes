"""Construit la proposition V3 à partir de la V2, sans toucher aux identités.

Transformations appliquées (voir CHANGELOG_V3.md) :
- registre : entrée core complète ;
- schéma unifié pour Core (identité au premier niveau) ;
- `inherits` + suppression des blocs identiques à defaults.yaml ;
- `tool_status` par outil (implemented / declared) ;
- `approval_matrix` par outil ;
- budget explicite (valeurs nulles, à trancher par le propriétaire) ;
- périmètre pour l'agent security ;
- métadonnées de version (updated_at, owner, changelog).

Les fichiers SOUL.md, AGENT.md et AGENT_SPEC.md sont copiés à l'identique :
aucune identité n'est modifiée.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import yaml

SRC = Path("/home/babayaga/.hermes/cache/scratch/audit_v2/kwes_agentic_team")
DST = Path("/home/babayaga/business/kwes/docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3")

IMPLEMENTED = {
    "web.search", "research.synthesis", "source.citation", "local.info.research",
    "service.compare", "lead.research", "web.page.read", "code.read",
    "code.write.workspace", "test.run.sandbox", "document.create",
    "profile.preference.read", "business.planning",
}

# Niveau minimal par famille d'outil. Volontairement conservateur : toute action
# qui produit un effet externe est classée A3 avec approbation explicite.
EXTERNAL = {
    "workflow.execute.authorized", "security.scan.authorized", "transaction.prepare",
    "image.generate.request", "message.draft.send", "deployment.prepare",
}
DRAFT = {
    "content.draft", "message.draft", "sales.proposal.draft", "support.response.draft",
    "business.report.create", "document.create", "workflow.design", "operations.plan",
    "marketing.strategy", "learning.plan", "daily.planning", "reminder.propose",
    "task.manage", "workflow.validate", "business.planning", "research.synthesis",
}
READ = {
    "web.search", "web.page.read", "source.citation", "local.info.research",
    "service.compare", "lead.research", "document.read", "document.extract",
    "document.convert", "calendar.read", "profile.preference.read", "code.read",
    "security.logs.read", "security.config.audit", "security.risk.report",
    "business.analysis", "business.kpi.read", "finance.analysis",
    "budget.read.authorized", "inventory.read.authorized", "order.status.read",
    "sales.pipeline.read", "customer.context.read.authorized", "image.analyze",
    "evidence.inspect", "result.verify", "quality.audit", "visual.quality_review",
    "seo.audit", "learning.assess", "learning.explain",
}
SANDBOX = {"code.write.workspace", "test.run.sandbox"}


def approval_for(tool: str) -> dict:
    if tool in EXTERNAL:
        return {"level": "A3", "approval": "explicit"}
    if tool in SANDBOX:
        return {"level": "A2", "approval": "policy_checked"}
    if tool in DRAFT:
        return {"level": "A1", "approval": "none"}
    if tool in READ:
        return {"level": "A0", "approval": "none"}
    return {"level": "A1", "approval": "none"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def normalize_core(data: dict) -> dict:
    """Aligne Core sur le schéma des spécialistes."""
    agent_block = data.pop("agent", {}) or {}
    out: dict = {
        "config_schema_version": data.pop("config_schema_version", "1.0.0"),
        "product": data.pop("product", "KWES"),
        "agent_id": agent_block.get("agent_id", "kwes.core"),
        "display_name": agent_block.get("display_name", "KWES"),
        "agent_type": "orchestrator",
        "version": "1.1.0",
        "status": "defined_not_activated",
    }
    out["authority"] = {
        "reports_to": None,
        "may_dispatch_agents": True,
        "may_change_user_permissions": True,
        "may_override_policy": False,
        "may_execute_outside_domain": True,
    }
    autonomy = data.get("autonomy") or {}
    out["autonomy"] = {
        "supported_levels": list((autonomy.get("levels") or {}).keys()) or ["A0", "A1", "A2", "A3", "A4"],
        "default_level": autonomy.get("default_level", "A1"),
        "max_level_without_confirmation": autonomy.get("max_level_without_confirmation", "A2"),
        "policy_engine_enforced_outside_model": autonomy.get("policy_engine_enforced_outside_model", True),
    }
    out["execution"] = data.pop("execution", {})
    out["execution"].setdefault("budget", {"max_tokens_per_task": None, "max_tool_calls": None, "max_cost_eur": None})
    # Le reste des blocs spécifiques à Core est conservé tel quel.
    for key in ("principles", "model_policy", "memory", "observability", "integrations",
                "orchestration", "delegation", "tool_loop_guardrails", "mission", "voice",
                "channels", "runtime", "browser", "security", "approvals", "finance",
                "telemetry", "data"):
        if key in data:
            out[key] = data[key]
    return out


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)

    # 1. Registre : entrée Core complète
    registry_path = DST / "registry/agents.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["core"] = {
        "agent_id": "kwes.core",
        "slug": "core",
        "name": "KWES",
        "domain": "Orchestration centrale",
        "config": "core/config.yaml",
        "soul": "core/SOUL.md",
        "agent": "core/AGENT.md",
        "spec": "core/AGENT_SPEC.md",
        "status": "defined_not_activated",
    }
    registry["config_version"] = "1.1.0"
    registry_path.write_text(
        yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    defaults = yaml.safe_load((SRC / "shared/config/defaults.yaml").read_text(encoding="utf-8"))
    identiques = 0

    # 2. Configurations
    for path in sorted(DST.rglob("config.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        is_core = path.parent.name == "core"
        if is_core:
            data = normalize_core(data)

        data["inherits"] = "shared/config/defaults.yaml"
        data["overrides"] = []
        data.setdefault("version", "1.1.0")
        data["updated_at"] = date(2026, 11, 19).isoformat()
        data.setdefault("owner", "Elfried Yobouet")

        # Blocs identiques à defaults.yaml : retirés, hérités désormais.
        for block in ("product", "environment", "status", "memory", "safety"):
            if data.get(block) == defaults.get(block):
                data.pop(block, None)
                identiques += 1
        if data.get("model_policy") == defaults.get("model_policy"):
            data.pop("model_policy", None)
            identiques += 1

        tools = (data.get("capabilities") or {}).get("declared_tool_ids") or []
        if tools:
            caps = data["capabilities"]
            caps["tool_status"] = {t: ("implemented" if t in IMPLEMENTED else "declared") for t in tools}
            caps["runtime_rule"] = "un outil au statut declared n'est jamais exposé au modèle"
            data["approval_matrix"] = {t: approval_for(t) for t in tools}

        execution = data.setdefault("execution", {})
        execution.setdefault(
            "budget", {"max_tokens_per_task": None, "max_tool_calls": 12, "max_cost_eur": None}
        )

        if data.get("agent_id") == "kwes.security":
            data["scope"] = {
                "authorized_assets": [],
                "requires_owner_signature": True,
                "out_of_scope_behavior": "refuse",
            }

        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # 3. Schéma de validation des configurations
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "kwes.agent.config",
        "type": "object",
        "required": ["agent_id", "agent_type", "version", "status", "inherits", "execution"],
        "properties": {
            "agent_id": {"type": "string", "pattern": "^kwes\\.[a-z]+$"},
            "agent_type": {"enum": ["orchestrator", "specialist"]},
            "version": {"type": "string"},
            "status": {"enum": ["defined_not_activated", "tested", "active", "retired"]},
            "inherits": {"type": "string"},
            "overrides": {"type": "array", "items": {"type": "string"}},
            "authority": {
                "type": "object",
                "required": ["may_dispatch_agents", "may_change_user_permissions", "may_override_policy"],
            },
            "capabilities": {
                "type": "object",
                "properties": {
                    "declared_tool_ids": {"type": "array", "items": {"type": "string"}},
                    "tool_status": {
                        "type": "object",
                        "additionalProperties": {"enum": ["implemented", "declared"]},
                    },
                },
            },
            "approval_matrix": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["level", "approval"],
                    "properties": {
                        "level": {"enum": ["A0", "A1", "A2", "A3", "A4"]},
                        "approval": {"enum": ["none", "policy_checked", "explicit", "strong"]},
                    },
                },
            },
            "execution": {
                "type": "object",
                "required": ["timeout_seconds", "max_retries"],
                "properties": {
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                    "max_retries": {"type": "integer", "minimum": 0, "maximum": 3},
                    "budget": {"type": "object"},
                },
            },
        },
    }
    (DST / "shared/contracts/agent-config.schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 4. Vérification : identités inchangées
    ecarts = []
    for path in SRC.rglob("*.md"):
        rel = path.relative_to(SRC)
        if digest(path) != digest(DST / rel):
            ecarts.append(str(rel))

    print("V3 écrite dans", DST)
    print("identités modifiées :", ecarts or "aucune")
    print("blocs hérités (retirés) :", identiques)
    return None


if __name__ == "__main__":
    main()

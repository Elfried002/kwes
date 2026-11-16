"""Policy Engine — décision d'autorisation indépendante du LLM.

Règles (docs/02-functional/BUSINESS_RULES.md, docs/08-security/SECURITY_MODEL.md) :
- R0 lecture : autorisé si la source/le domaine est autorisé.
- R1 préparation locale réversible : autorisé.
- R2 communication / modification externe : approbation ponctuelle requise.
- R3 engagement financier/légal : refusé dans l'Alpha (aucun paiement exécuté).
- R4 opération dangereuse : toujours refusé.
- Capacité inconnue : refus par défaut.

Le niveau de risque n'est jamais celui déclaré par le modèle : le moteur part
de la politique codée en dur du skill, puis applique une escalade sur les
drapeaux/actions présents dans l'entrée. Le niveau déclaré par le LLM ne peut
que relever le risque, jamais l'abaisser.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from app.core.config import Settings

logger = logging.getLogger("kwes.policy")

RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}


def max_risk(*levels: str | None) -> str:
    best = "R0"
    for level in levels:
        if level and level in RISK_ORDER and RISK_ORDER[level] > RISK_ORDER[best]:
            best = level
    return best


@dataclass(frozen=True)
class SkillPolicy:
    risk: str
    permissions: frozenset[str]
    network: bool = False


@dataclass(frozen=True)
class ActionPolicy:
    risk: str
    permissions: frozenset[str] = frozenset()
    requires_approval: bool = False
    network: bool = False


# Politiques codées en dur : un manifeste ne peut pas élargir ces droits.
SKILL_POLICIES: dict[str, SkillPolicy] = {
    "web_research": SkillPolicy("R0", frozenset({"web.search", "web.read"}), network=True),
    "business_planning": SkillPolicy("R1", frozenset({"local.write"}), network=False),
    "browser_readonly": SkillPolicy("R0", frozenset({"browser.read", "web.read"}), network=True),
    # Capacités conversationnelles : écriture locale réversible, jamais d'action
    # externe. Le policy engine les autorise sans approbation, comme toute R1.
    "remember": SkillPolicy("R1", frozenset({"local.write"}), network=False),
    "document_write": SkillPolicy("R1", frozenset({"local.write"}), network=False),
}

ACTION_POLICIES: dict[str, ActionPolicy] = {
    "external.publish": ActionPolicy("R2", frozenset({"external.publish"}), True),
    "email.send": ActionPolicy("R2", frozenset({"email.send"}), True),
    "crm.update": ActionPolicy("R2", frozenset({"crm.write"}), True),
    "file.delete": ActionPolicy("R2", frozenset({"local.delete"}), True),
    "payment.charge": ActionPolicy("R3", frozenset({"payment.charge"}), True),
    "payment.transfer": ActionPolicy("R3", frozenset({"payment.transfer"}), True),
    "contract.sign": ActionPolicy("R3", frozenset({"legal.sign"}), True),
    "secrets.read": ActionPolicy("R4", frozenset({"secrets.read"})),
    "policy.modify": ActionPolicy("R4", frozenset({"policy.write"})),
    "audit.delete": ActionPolicy("R4", frozenset({"audit.delete"})),
}

_EXTERNAL_FLAGS = {
    "publish",
    "publish_external",
    "external_publish",
    "send",
    "send_external",
    "send_email",
    "share_external",
    "post_external",
}
_FINANCIAL_FLAGS = {
    "payment",
    "charge",
    "purchase",
    "transfer",
    "subscribe",
    "pay",
    "amount",
    "checkout",
}
_INSTRUCTION_FIELDS = ("objective", "query", "instruction", "prompt", "message", "goal")

# Marqueurs d'injection / d'action interdite dans une instruction utilisateur.
_DANGER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ignore[rz]?\s+(les\s+|all\s+)?(previous\s+|pr[ée]c[ée]dentes?\s+)?instructions", re.I), "instruction_override"),
    (re.compile(r"system\s*prompt|prompt\s*syst[èe]me", re.I), "system_prompt_extraction"),
    (re.compile(r"exfiltr|exfiltrer|extract.*(secret|api[_\s-]?key)", re.I), "secret_exfiltration"),
    (re.compile(r"bypass|contourn.*(s[ée]curit[ée]|policy|permission)", re.I), "security_bypass"),
    (re.compile(r"d[ée]sactive[rz]?\s+(la\s+)?s[ée]curit[ée]|disable\s+(the\s+)?(security|policy)", re.I), "security_bypass"),
    (re.compile(r"supprim\w*\s+(les\s+)?(preuves?|logs?|audit)|delete\s+(the\s+)?(audit|logs?)", re.I), "evidence_deletion"),
    (re.compile(r"rm\s+-rf\s+/", re.I), "destructive_command"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)", re.I), "secret_material"),
)


@dataclass(frozen=True)
class ApprovalLike:
    """Vue minimale d'une approbation pour le moteur (évite un couplage ORM)."""

    status: str
    payload_hash: str
    expires_at: datetime | None = None
    decided_at: datetime | None = None

    def is_usable_at(self, moment: datetime) -> bool:
        if self.status != "approved" or not self.decided_at:
            return False
        if self.expires_at is None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > moment


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    risk: str
    allowed: bool
    requires_approval: bool
    code: str  # ALLOW | APPROVAL_REQUIRED | FORBIDDEN
    reason: str
    permissions: tuple[str, ...] = ()
    findings: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "risk": self.risk,
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "code": self.code,
            "reason": self.reason,
            "permissions": list(self.permissions),
            "findings": list(self.findings),
        }


class PolicyEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- Domaines -------------------------------------------------------
    def is_domain_allowed(self, domain: str) -> bool:
        host = (domain or "").strip().lower().rstrip(".")
        if not host or "/" in host or "@" in host:
            return False
        allowlist = self.settings.browser_domain_allowlist
        return any(host == allowed or host.endswith("." + allowed) for allowed in allowlist)

    def check_domains(self, domains: Iterable[str]) -> tuple[bool, str]:
        for domain in domains:
            if not self.is_domain_allowed(domain):
                return False, f"Domaine non autorisé: {domain}"
        return True, ""

    # -- Analyse d'entrée ------------------------------------------------
    def _scan_instructions(self, inputs: Mapping[str, Any]) -> list[str]:
        findings: list[str] = []
        for field_name in _INSTRUCTION_FIELDS:
            value = inputs.get(field_name)
            if not isinstance(value, str):
                continue
            for pattern, label in _DANGER_PATTERNS:
                if pattern.search(value):
                    findings.append(f"{label}:{field_name}")
        # Un contenu "untrusted" repris d'une page ne doit jamais être réinjecté
        # comme instruction : on le signale mais il n'élève pas seul le risque.
        return findings

    def _escalate_from_inputs(self, inputs: Mapping[str, Any]) -> tuple[str, list[str]]:
        risk = "R0"
        findings: list[str] = []
        for key, value in inputs.items():
            lowered = str(key).lower()
            if lowered in _EXTERNAL_FLAGS and (value is True or value == "true"):
                risk = max_risk(risk, "R2")
                findings.append(f"external_flag:{key}")
            if lowered in _FINANCIAL_FLAGS and value is True:
                risk = max_risk(risk, "R3")
                findings.append(f"financial_flag:{key}")
            if lowered == "action" and isinstance(value, str) and value in ACTION_POLICIES:
                risk = max_risk(risk, ACTION_POLICIES[value].risk)
                findings.append(f"action:{value}")
            if lowered == "risk" and isinstance(value, str):
                risk = max_risk(risk, value)
        for finding in self._scan_instructions(inputs):
            risk = max_risk(risk, "R4")
            findings.append(finding)
        return risk, findings

    # -- Évaluation -------------------------------------------------------
    def _decide(
        self,
        *,
        action: str,
        risk: str,
        permissions: Sequence[str],
        approval: ApprovalLike | None,
        approval_payload_hash: str | None,
    ) -> PolicyDecision:
        perms = tuple(sorted(set(permissions)))
        if risk == "R4":
            return PolicyDecision(
                action, risk, False, False, "FORBIDDEN",
                "Opération interdite par la politique de sécurité.", perms,
            )
        if risk == "R3":
            return PolicyDecision(
                action, risk, False, False, "FORBIDDEN",
                "Les engagements financiers ou légaux ne sont pas exécutables dans l'Alpha.", perms,
            )
        if risk == "R2":
            usable = (
                approval is not None
                and approval.is_usable_at(datetime.now(timezone.utc))
                and (approval_payload_hash is None or approval.payload_hash == approval_payload_hash)
            )
            if usable:
                return PolicyDecision(
                    action, risk, True, False, "ALLOW",
                    "Action externe autorisée par une approbation valide.", perms,
                )
            return PolicyDecision(
                action, risk, False, True, "APPROVAL_REQUIRED",
                "Cette action externe requiert une approbation explicite.", perms,
            )
        return PolicyDecision(action, risk, True, False, "ALLOW", "Action autorisée.", perms)

    def evaluate_skill_call(
        self,
        *,
        skill: str,
        inputs: Mapping[str, Any] | None = None,
        declared_risk: str | None = None,
        domains: Sequence[str] | None = None,
        approval: ApprovalLike | None = None,
        approval_payload_hash: str | None = None,
    ) -> PolicyDecision:
        inputs = dict(inputs or {})
        policy = SKILL_POLICIES.get(skill)
        if policy is None:
            decision = PolicyDecision(
                f"skill:{skill}", "R4", False, False, "FORBIDDEN",
                "Capacité inconnue : refus par défaut.",
            )
            self._log(decision)
            return decision

        escalated, findings = self._escalate_from_inputs(inputs)
        risk = max_risk(policy.risk, declared_risk, escalated)

        if policy.network and domains:
            allowed, reason = self.check_domains(domains)
            if not allowed:
                decision = PolicyDecision(
                    f"skill:{skill}", risk, False, False, "FORBIDDEN", reason,
                    tuple(sorted(policy.permissions)), tuple(findings),
                )
                self._log(decision)
                return decision

        decision = self._decide(
            action=f"skill:{skill}",
            risk=risk,
            permissions=policy.permissions,
            approval=approval,
            approval_payload_hash=approval_payload_hash,
        )
        if findings:
            decision = PolicyDecision(
                decision.action, decision.risk, decision.allowed,
                decision.requires_approval, decision.code, decision.reason,
                decision.permissions, tuple(findings),
            )
        self._log(decision)
        return decision

    def evaluate_action(
        self,
        action: str,
        *,
        approval: ApprovalLike | None = None,
        approval_payload_hash: str | None = None,
        domain: str | None = None,
    ) -> PolicyDecision:
        policy = ACTION_POLICIES.get(action)
        if policy is None:
            decision = PolicyDecision(
                action, "R4", False, False, "FORBIDDEN",
                "Action inconnue : refus par défaut.",
            )
            self._log(decision)
            return decision
        if policy.network and domain and not self.is_domain_allowed(domain):
            decision = PolicyDecision(
                action, policy.risk, False, False, "FORBIDDEN",
                f"Domaine non autorisé: {domain}", tuple(sorted(policy.permissions)),
            )
            self._log(decision)
            return decision
        decision = self._decide(
            action=action,
            risk=policy.risk if policy.risk != "R2" or policy.requires_approval else max_risk(policy.risk, "R2"),
            permissions=policy.permissions,
            approval=approval,
            approval_payload_hash=approval_payload_hash,
        )
        self._log(decision)
        return decision

    def _log(self, decision: PolicyDecision) -> None:
        logger.info(
            "policy decision action=%s risk=%s code=%s allowed=%s approval=%s findings=%s",
            decision.action,
            decision.risk,
            decision.code,
            decision.allowed,
            decision.requires_approval,
            ",".join(decision.findings) or "-",
        )

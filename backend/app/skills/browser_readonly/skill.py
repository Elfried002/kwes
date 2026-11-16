"""Skill browser_readonly — lecture seule d'une page autorisée.

IMPLÉMENTATION : Playwright n'est pas installé dans cet environnement, donc ce
skill utilise httpx + extraction HTML lisible côté serveur (pas de rendu JS).
Ce choix est explicite et documenté : voir backend/README.md §Limites.
Sécurité : allowlist de domaines, blocage IP privées/localhost/metadata,
redirections revalidées, contenu traité comme non fiable.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.skills.base import (
    SkillContext,
    SkillProviderError,
    SkillResult,
    SkillValidationError,
)
from app.skills.fetch import extract_readable, validate_url_shape

MAX_LINKS = 20


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    url = str(payload["url"]).strip()
    objective = payload.get("objective") or ""
    max_chars = int(payload.get("max_chars") or 8000)

    # Validation statique immédiate (avant tout accès réseau injecté). En mode
    # web ouvert, seule la validation SSRF subsiste : pas de liste de domaines.
    validated = validate_url_shape(
        url, ctx.allowlist, enforce_allowlist=not getattr(ctx.settings, "browser_open_web", False)
    )
    ctx.logger.info("browser_readonly url=%s", validated[:160])

    try:
        page = await ctx.fetch(validated)
    except SkillValidationError:
        raise
    except Exception as exc:
        raise SkillProviderError("Page inaccessible.") from exc

    if page.status >= 400:
        raise SkillProviderError(
            "La page a renvoyé une erreur HTTP.",
            details={"status": page.status},
        )

    extracted = extract_readable(page.text, page.final_url or validated)
    if not extracted.text.strip():
        raise SkillProviderError("Aucun contenu lisible extrait de la page.")

    content = extracted.text[:max_chars]
    links = extracted.links[:MAX_LINKS]
    host = urlsplit(page.final_url or validated).hostname or ""

    output = {
        "url": validated,
        "final_url": page.final_url or validated,
        "title": extracted.title or host,
        "content": content,
        "links": links,
        "status": page.status,
        "truncated": len(extracted.text) > len(content),
        "injection_detected": bool(extracted.injection_findings),
        "untrusted": True,
    }
    summary = (
        f"Page « {output['title']} » lue ({len(content)} caractères, {len(links)} lien(s))."
        + (" Contenu hostile neutralisé et signalé." if output["injection_detected"] else "")
        + (f" Objectif de lecture : {objective}" if objective else "")
    )
    return SkillResult(
        output=output,
        summary=summary,
        evidence=[{"type": "page", "url": output["final_url"], "status": page.status}],
    )

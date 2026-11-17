"""Skill document_write — produit un document texte, stocké en base sous l'utilisateur.

Écriture locale réversible (R1), aucun réseau, aucune publication externe.
Le document est ensuite lisible et téléchargeable par son seul propriétaire via
`GET /api/v1/documents/{id}` et `GET /api/v1/documents/{id}/download`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from app.db.models import Document
from app.skills.base import SkillContext, SkillError, SkillResult

FORMATS = {"markdown": ".md", "text": ".txt"}
MAX_CONTENT_CHARS = 200_000
PREVIEW_CHARS = 240


@asynccontextmanager
async def _session_for(ctx: SkillContext):
    if ctx.session is not None:
        yield ctx.session
        return
    if ctx.db is None:
        raise SkillError("Documents indisponibles : base de données non attachée au contexte.")
    async with ctx.db.session() as session:
        yield session


def _sources_section(context: str) -> str:
    """Construit une section « sources lues » à partir du résultat de recherche.

    Aucune phrase n'est inventée : on reprend les titres, domaines et extraits
    réellement collectés par l'étape amont.
    """
    import json

    try:
        data = json.loads(context)
    except (TypeError, ValueError):
        return ""
    sources = data.get("sources") if isinstance(data, dict) else None
    if not sources:
        return ""
    lines = ["", "## Sources consultées", ""]
    for index, source in enumerate(sources[:8], start=1):
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or source.get("domain") or "Source").strip()
        url = str(source.get("url") or "").strip()
        status = str(source.get("status") or "")
        snippet = " ".join(str(source.get("snippet") or "").split())[:220]
        marker = "lue" if status == "lue" else status or "trouvée"
        lines.append(f"{index}. **{title}** — {url} ({marker})")
        if snippet:
            lines.append(f"   > {snippet}")
    lines.append("")
    lines.append(
        "Ces éléments proviennent des pages effectivement récupérées ; ils restent "
        "à vérifier à la source avant toute décision."
    )
    return "\n".join(lines)


INSTRUCTION_MARKERS = (
    "contenu complet",
    "texte complet",
    "rédige",
    "redige",
    "à rédiger",
    "a rediger",
    "document doit",
)


def _synthesis_body(context: str) -> str:
    """Reprend la synthèse réellement produite par l'étape de recherche amont.

    Aucune phrase n'est ajoutée : on réutilise le texte sourcé déjà calculé quand
    le modèle n'a fourni qu'une consigne au lieu d'un corps de document.
    """
    import json

    try:
        data = json.loads(context)
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    synthesis = data.get("synthesis")
    if not isinstance(synthesis, str):
        return ""
    text = synthesis.strip()
    return text if len(text) >= 200 else ""


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    title = " ".join(str(payload.get("title") or "").split())
    content = str(payload.get("content") or "").replace("\r\n", "\n").strip()
    context = str(payload.get("context") or "")
    if context:
        # Le planificateur produit parfois une consigne au lieu d'un corps : on
        # reprend alors la synthèse sourcée de l'étape amont, jamais du texte inventé.
        body = _synthesis_body(context)
        looks_like_instruction = content.lower().startswith(INSTRUCTION_MARKERS) or len(content) < 250
        if body and looks_like_instruction:
            content = body
        # La traçabilité des pages réellement lues est systématique.
        extra = _sources_section(context)
        if extra and "## Sources consultées" not in content:
            content = (content + "\n" + extra).strip()
    fmt = str(payload.get("format") or "markdown")

    if len(title) < 3:
        raise SkillError("Titre de document trop court.")
    if not content:
        raise SkillError("Le document est vide : rien à enregistrer.")
    if fmt not in FORMATS:
        fmt = "markdown"
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS].rstrip()

    async with _session_for(ctx) as session:
        document = Document(
            user_id=ctx.user_id,
            title=title[:160],
            format=fmt,
            content=content,
            chars=len(content),
            source="agent",
        )
        session.add(document)
        await session.commit()
        document_id = str(document.id)

    preview = " ".join(content.split())[:PREVIEW_CHARS]
    summary = f"Document « {title[:80]} » enregistré ({len(content)} caractères, {fmt})."
    ctx.logger.info("document_write id=%s chars=%s user=%s", document_id, len(content), ctx.user_id)
    return SkillResult(
        output={
            "document_id": document_id,
            "title": title[:160],
            "format": fmt,
            "chars": len(content),
            "preview": preview,
        },
        summary=summary,
        evidence=[{"type": "document", "id": document_id, "chars": len(content)}],
    )

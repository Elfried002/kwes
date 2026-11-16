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


async def run(payload: dict[str, Any], ctx: SkillContext) -> SkillResult:
    title = " ".join(str(payload.get("title") or "").split())
    content = str(payload.get("content") or "").replace("\r\n", "\n").strip()
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

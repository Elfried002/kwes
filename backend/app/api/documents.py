"""Documents de l'utilisateur : liste, lecture, téléchargement, suppression.

Un document n'est visible que par son propriétaire (`user_id`), côté API comme
côté RLS. Aucune route publique, aucun partage implicite.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.api.deps import PageDep, SessionDep, TenantDep, UserDep
from app.api.serializers import document_dict
from app.core.errors import NotFound
from app.db.models import Document

router = APIRouter(tags=["documents"])

MEDIA_TYPES = {"markdown": "text/markdown; charset=utf-8", "text": "text/plain; charset=utf-8"}
EXTENSIONS = {"markdown": "md", "text": "txt"}


async def _owned_document(session, tenant, document_id: uuid.UUID) -> Document:
    row = await session.get(Document, document_id)
    if row is None or row.tenant_id != tenant.id:
        raise NotFound("Document introuvable.")
    return row


@router.get("/documents")
async def list_documents(
    response: Response,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    page: PageDep,
    q: str | None = Query(default=None, max_length=120),
) -> list[dict[str, Any]]:
    stmt = select(Document).where(Document.tenant_id == tenant.id)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))
    rows = (
        await session.execute(
            stmt.order_by(Document.created_at.desc()).limit(page.limit).offset(page.offset)
        )
    ).scalars().all()
    total = (
        await session.execute(select(func.count(Document.id)).where(Document.tenant_id == tenant.id))
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    return [document_dict(row) for row in rows]


@router.get("/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID, user: UserDep, tenant: TenantDep, session: SessionDep
) -> dict[str, Any]:
    row = await _owned_document(session, tenant, document_id)
    return document_dict(row, include_content=True)


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    user: UserDep,
    tenant: TenantDep,
    session: SessionDep,
    format: str | None = Query(default=None, pattern="^(docx|pdf)$"),
) -> Response:
    """Télécharge le document : texte brut par défaut, Word ou PDF à la demande.

    La conversion est calculée ici, donc rien n'est dupliqué en base et un
    document ancien profite immédiatement des nouveaux formats.
    """
    row = await _owned_document(session, tenant, document_id)
    extension = EXTENSIONS.get(row.format, "txt")
    safe_title = "".join(
        char if char.isalnum() or char in " -_" else "-" for char in row.title
    ).strip() or "document"
    demande = (format or "").lower()
    if demande in {"docx", "pdf"}:
        from app.documents.export import to_docx, to_pdf

        try:
            octets = to_docx(row.title, row.content) if demande == "docx" else to_pdf(row.title, row.content)
        except Exception as erreur:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail="Conversion du document impossible."
            ) from erreur
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if demande == "docx"
            else "application/pdf"
        )
        return Response(
            content=octets,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title[:80]}.{demande}"'
            },
        )
    return PlainTextResponse(
        content=row.content,
        media_type=MEDIA_TYPES.get(row.format, "text/plain; charset=utf-8"),
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title[:80]}.{extension}"'
        },
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, user: UserDep, tenant: TenantDep, session: SessionDep
) -> Response:
    row = await _owned_document(session, tenant, document_id)
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)

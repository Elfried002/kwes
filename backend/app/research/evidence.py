"""Registre de preuves : ce que Kwes a réellement lu.

Règle : une ligne n'est créée qu'après une extraction réussie. Une URL trouvée
par un moteur n'est jamais une preuve.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid

from sqlalchemy import select

from app.core.utils import utcnow
from app.db.base import Database
from app.db.models import Evidence

logger = logging.getLogger("kwes.research.evidence")

_WS = re.compile(r"\s+")


def content_fingerprint(text: str) -> str:
    """Empreinte stable : le contenu est normalisé avant hachage."""
    normalized = _WS.sub(" ", text or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_excerpt(text: str, limit: int = 400) -> str:
    cleaned = _WS.sub(" ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    # Coupe sur une frontière de phrase quand c'est possible.
    for separator in (". ", "! ", "? "):
        index = cut.rfind(separator)
        if index > limit * 0.5:
            return cut[: index + 1].strip()
    return cut.strip() + "…"


async def record(
    db: Database,
    *,
    user_id: uuid.UUID,
    task_id: uuid.UUID | None,
    url: str,
    canonical_url: str,
    domain: str,
    title: str | None,
    content: str,
    provider: str,
    status: str = "ok",
    published_at=None,
    provenance: dict | None = None,
) -> str | None:
    """Enregistre (ou rafraîchit) une preuve. Renvoie son identifiant."""
    fingerprint = content_fingerprint(content)
    excerpt = build_excerpt(content)
    async with db.session() as session:
        existing = (
            await session.execute(
                select(Evidence).where(
                    Evidence.user_id == user_id, Evidence.content_hash == fingerprint
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.fetched_at = utcnow()
            existing.excerpt = excerpt or existing.excerpt
            existing.extraction_status = status
            await session.commit()
            return str(existing.id)
        row = Evidence(
            user_id=user_id,
            task_id=task_id,
            url=url,
            canonical_url=canonical_url,
            domain=domain,
            title=(title or "")[:500] or None,
            excerpt=excerpt,
            content=content[:200_000],
            content_hash=fingerprint,
            provider=provider,
            extraction_status=status,
            published_at=published_at,
            fetched_at=utcnow(),
            provenance=provenance or {},
        )
        session.add(row)
        try:
            await session.commit()
        except Exception:  # noqa: BLE001 — course sur l'index unique
            await session.rollback()
            logger.info("Preuve déjà enregistrée (course) url=%s", canonical_url[:120])
            return None
        return str(row.id)


async def list_for_user(db: Database, user_id: uuid.UUID, limit: int = 20) -> list[dict]:
    async with db.session() as session:
        rows = (
            await session.execute(
                select(Evidence)
                .where(Evidence.user_id == user_id)
                .order_by(Evidence.fetched_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": str(row.id),
            "url": row.url,
            "canonical_url": row.canonical_url,
            "domain": row.domain,
            "title": row.title,
            "excerpt": row.excerpt,
            "provider": row.provider,
            "extraction_status": row.extraction_status,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
        }
        for row in rows
    ]

"""Extraction de contenu : pages web (Chromium/httpx) et PDF (pypdf).

Un PDF image (scanné) n'est PAS de l'OCR : il est signalé comme
« sans texte extractible ». L'OCR appartient à P3.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from app.skills.base import SkillError

logger = logging.getLogger("kwes.research.extract")

MIN_TEXT_CHARS = 80


@dataclass(slots=True)
class PdfExtraction:
    text: str
    pages: list[tuple[int, str]] = field(default_factory=list)
    status: str = "ok"  # ok | sans_texte | chiffré | invalide | trop_volumineux
    error: str | None = None

    @property
    def has_text(self) -> bool:
        return self.status == "ok" and len(self.text.strip()) >= MIN_TEXT_CHARS


def looks_like_pdf(data: bytes, content_type: str | None = None) -> bool:
    if data[:5] == b"%PDF-":
        return True
    return bool(content_type and "application/pdf" in content_type.lower())


def extract_pdf(
    data: bytes,
    *,
    max_bytes: int = 8_000_000,
    max_pages: int = 40,
) -> PdfExtraction:
    """Extrait le texte page par page, en conservant le numéro de page."""
    if len(data) > max_bytes:
        return PdfExtraction(
            text="",
            status="trop_volumineux",
            error=f"PDF trop volumineux ({len(data) // 1024} Ko > {max_bytes // 1024} Ko).",
        )
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dépendance déclarée
        return PdfExtraction(text="", status="invalide", error="pypdf n'est pas installé.")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                # Beaucoup de PDF « protégés » ont un mot de passe vide.
                if not reader.decrypt(""):
                    return PdfExtraction(
                        text="",
                        status="chiffré",
                        error="PDF chiffré : mot de passe requis.",
                    )
            except Exception:  # noqa: BLE001
                return PdfExtraction(text="", status="chiffré", error="PDF chiffré : mot de passe requis.")
        page_count = len(reader.pages)
        pages: list[tuple[int, str]] = []
        chunks: list[str] = []
        for index in range(min(page_count, max_pages)):
            try:
                page_text = reader.pages[index].extract_text() or ""
            except Exception as exc:  # noqa: BLE001 — page illisible isolée
                logger.warning("PDF page %s illisible (%s)", index + 1, type(exc).__name__)
                page_text = ""
            cleaned = " ".join(page_text.split())
            if cleaned:
                pages.append((index + 1, cleaned))
                chunks.append(f"[page {index + 1}] {cleaned}")
        text = "\n\n".join(chunks)
        if len(text.strip()) < MIN_TEXT_CHARS:
            return PdfExtraction(
                text=text,
                pages=pages,
                status="sans_texte",
                error="PDF sans texte extractible (probablement numérisé) : OCR non pris en charge en P1.",
            )
        if page_count > max_pages:
            text += f"\n\n[document tronqué : {max_pages} pages sur {page_count}]"
        return PdfExtraction(text=text, pages=pages, status="ok")
    except Exception as exc:  # noqa: BLE001 — pypdf lève des erreurs variées
        return PdfExtraction(
            text="",
            status="invalide",
            error=f"PDF illisible ({type(exc).__name__}).",
        )


async def fetch_bytes(fetcher, url: str, *, max_bytes: int) -> tuple[bytes, str | None]:
    """Récupère un binaire (PDF) via le fetcher de skills, sans dépasser la limite."""
    page = await fetcher(url)
    raw = getattr(page, "raw", None) or getattr(page, "content", None)
    if raw is None:
        raise SkillError("Contenu binaire indisponible pour ce document.")
    if len(raw) > max_bytes:
        raise SkillError("Document trop volumineux.")
    return raw, getattr(page, "content_type", None)

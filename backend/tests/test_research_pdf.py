"""Extraction PDF : texte, pages, chiffrement, fichier illisible, PDF image."""

from __future__ import annotations

import io

import pytest

from app.research.extract import extract_pdf, looks_like_pdf


def _build_pdf(text: str, pages: int = 1) -> bytes:
    """Construit un PDF minimal valide (Helvetica) avec une table xref correcte."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    font_obj = 3 + pages * 2
    for index in range(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({text} page {index + 1}) Tj ET".encode()
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {4 + index * 2} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    return out.getvalue()


def _build_encrypted_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(_build_pdf("Secret")))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("motdepasse")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _build_image_only_pdf() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_looks_like_pdf_by_magic_bytes() -> None:
    assert looks_like_pdf(b"%PDF-1.7 ...") is True
    assert looks_like_pdf(b"<html>") is False
    assert looks_like_pdf(b"xx", "application/pdf; charset=binary") is True


LONG_TEXT = (
    "Rapport annuel sur les assistants vocaux en Afrique de l Ouest : usages, freins et opportunites pour les entreprises locales. "
    "Cette etude couvre plusieurs marches et s appuie sur des entretiens."
)


def test_text_pdf_is_extracted_with_page_numbers() -> None:
    result = extract_pdf(_build_pdf(LONG_TEXT, pages=2))
    assert result.status == "ok", result.error
    assert "[page 1]" in result.text and "[page 2]" in result.text
    assert len(result.pages) == 2
    assert "Rapport annuel" in result.text


def test_encrypted_pdf_is_reported_not_crashed() -> None:
    result = extract_pdf(_build_encrypted_pdf())
    assert result.status == "chiffré"
    assert "mot de passe" in (result.error or "")


def test_image_only_pdf_is_not_pretended_to_be_ocr() -> None:
    result = extract_pdf(_build_image_only_pdf())
    assert result.status == "sans_texte"
    assert "OCR" in (result.error or "")


def test_malformed_pdf_is_rejected() -> None:
    result = extract_pdf(b"%PDF-1.4 n'importe quoi")
    assert result.status in ("invalide", "sans_texte")


def test_oversized_pdf_is_refused() -> None:
    result = extract_pdf(_build_pdf("x"), max_bytes=10)
    assert result.status == "trop_volumineux"


def test_page_limit_truncates_with_notice() -> None:
    result = extract_pdf(_build_pdf(LONG_TEXT, pages=5), max_pages=2)
    assert result.status == "ok"
    assert "tronqué" in result.text

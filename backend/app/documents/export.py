"""Export d'un document stocké vers Word (.docx) et PDF.

Le contenu en base reste du markdown ou du texte : l'export est calculé à la
demande, donc aucun changement de schéma et aucun format dupliqué en base.
"""

from __future__ import annotations

import io
import re

TITRE_MAX = 120


def _lignes(contenu: str) -> list[tuple[str, str]]:
    """Découpe en (style, texte) : titre, sous-titre, puce, paragraphe, vide."""
    resultat: list[tuple[str, str]] = []
    for brute in contenu.splitlines():
        ligne = brute.rstrip()
        if not ligne.strip():
            resultat.append(("vide", ""))
        elif ligne.startswith("### "):
            resultat.append(("h3", ligne[4:].strip()))
        elif ligne.startswith("## "):
            resultat.append(("h2", ligne[3:].strip()))
        elif ligne.startswith("# "):
            resultat.append(("h1", ligne[2:].strip()))
        elif ligne.lstrip().startswith(("- ", "* ", "• ")):
            resultat.append(("puce", ligne.lstrip()[2:].strip()))
        else:
            resultat.append(("paragraphe", ligne.strip()))
    return resultat


def _nettoyer_markdown(texte: str) -> str:
    texte = re.sub(r"\*\*(.+?)\*\*", r"\1", texte)
    texte = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", texte)
    texte = re.sub(r"`([^`]+)`", r"\1", texte)
    texte = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", texte)
    return texte


def to_docx(titre: str, contenu: str) -> bytes:
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.add_heading(titre[:TITRE_MAX] or "Document", level=0)
    for style, texte in _lignes(contenu):
        if style == "vide":
            continue
        propre = _nettoyer_markdown(texte)
        if style in {"h1", "h2", "h3"}:
            document.add_heading(propre, level={"h1": 1, "h2": 2, "h3": 3}[style])
        elif style == "puce":
            document.add_paragraph(propre, style="List Bullet")
        else:
            paragraphe = document.add_paragraph(propre)
            paragraphe.paragraph_format.space_after = Pt(6)
    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


def to_pdf(titre: str, contenu: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    tampon = io.BytesIO()
    doc = SimpleDocTemplate(
        tampon,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=titre[:TITRE_MAX] or "Document",
    )
    base = getSampleStyleSheet()
    styles = {
        "titre": ParagraphStyle("KwesTitre", parent=base["Title"], fontSize=20, leading=24),
        "h1": ParagraphStyle("KwesH1", parent=base["Heading1"], fontSize=15, leading=19),
        "h2": ParagraphStyle("KwesH2", parent=base["Heading2"], fontSize=13, leading=17),
        "h3": ParagraphStyle("KwesH3", parent=base["Heading3"], fontSize=11.5, leading=15),
        "corps": ParagraphStyle("KwesCorps", parent=base["BodyText"], fontSize=10.5, leading=15),
        "puce": ParagraphStyle(
            "KwesPuce", parent=base["BodyText"], fontSize=10.5, leading=15,
            leftIndent=12, bulletIndent=2,
        ),
    }
    flux: list[object] = [Paragraph(escape(titre[:TITRE_MAX] or "Document"), styles["titre"]), Spacer(1, 8)]
    for style, texte in _lignes(contenu):
        if style == "vide":
            flux.append(Spacer(1, 6))
            continue
        propre = escape(_nettoyer_markdown(texte))
        if style in styles:
            flux.append(Paragraph(propre, styles[style]))
        else:
            flux.append(Paragraph(propre, styles["corps"]))
    doc.build(flux)
    return tampon.getvalue()

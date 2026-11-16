"""Registre des langues vocales de Kwes.

Trois statuts seulement, et aucun ne s'obtient sans mesure :

- `validated`  : une phrase de référence a été prononcée puis relue par le
  modèle avec une similarité mesurée, et la phrase est validée par un locuteur
  natif ;
- `experimental` : le modèle produit et comprend quelque chose, mais la qualité
  ou la phrase de test n'est pas encore validée ;
- `unavailable` : aucun audio exploitable, ou langue non couverte.

Les mesures proviennent de `tools/voice_languages_probe.py` (voir
`docs/LANGUES_VOIX.md`). Ne jamais passer une langue en `validated` sur la seule
foi de la documentation du fournisseur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STATUS_VALIDATED = "validated"
STATUS_EXPERIMENTAL = "experimental"
STATUS_UNAVAILABLE = "unavailable"

STATUS_LABELS = {
    STATUS_VALIDATED: "Support validé",
    STATUS_EXPERIMENTAL: "Support expérimental",
    STATUS_UNAVAILABLE: "Non disponible",
}


@dataclass(frozen=True)
class VoiceLanguage:
    code: str
    label: str
    family: str
    status: str
    asr: bool
    tts: bool
    phrase: str | None
    evidence: str
    native_review: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "family": self.family,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "asr": self.asr,
            "tts": self.tts,
            "phrase": self.phrase,
            "evidence": self.evidence,
            "native_review": self.native_review,
        }


# Rempli à partir des mesures du 16/11 (voir docs/LANGUES_VOIX.md).
LANGUAGES: tuple[VoiceLanguage, ...] = (
    VoiceLanguage(
        code="fr",
        label="Français",
        family="prioritaire",
        status=STATUS_VALIDATED,
        asr=True,
        tts=True,
        phrase="Bonjour, je suis Kwes, ton assistant personnel.",
        evidence="Conversation réelle : question transcrite mot pour mot ; phrase de test rendue à l'identique, relue à 0,99.",
        native_review=True,
    ),
    VoiceLanguage(
        code="en",
        label="Anglais",
        family="prioritaire",
        status=STATUS_EXPERIMENTAL,
        asr=True,
        tts=True,
        phrase="Hello, I am Kwes, your personal assistant.",
        evidence="Phrase rendue à l'identique, relue à 0,94 — conversation complète non encore testée.",
    ),
    VoiceLanguage(
        code="sw",
        label="Swahili",
        family="prioritaire",
        status=STATUS_EXPERIMENTAL,
        asr=True,
        tts=True,
        phrase="Habari, mimi ni Kwes, msaidizi wako binafsi.",
        evidence="Phrase rendue à l'identique, relue à 0,99 ; phrase à valider par un locuteur natif.",
    ),
    VoiceLanguage(
        code="yo",
        label="Yoruba",
        family="prioritaire",
        status=STATUS_EXPERIMENTAL,
        asr=True,
        tts=True,
        phrase="Báwo ni, èmi ni Kwes, olùrànlọ́wọ́ rẹ.",
        evidence="Rendu exact avec tons ; relecture à 0,77 — le nom est entendu « Quest », tons non restitués.",
    ),
    VoiceLanguage(
        code="ha",
        label="Hausa",
        family="prioritaire",
        status=STATUS_EXPERIMENTAL,
        asr=True,
        tts=True,
        phrase="Sannu, ni ne Kwes, mataimakin ka.",
        evidence="Phrase rendue et relue à l'identique (1,00) ; validation par un locuteur natif en attente.",
    ),
    VoiceLanguage(
        code="wo",
        label="Wolof",
        family="prioritaire",
        status=STATUS_EXPERIMENTAL,
        asr=True,
        tts=True,
        phrase="Salaam, man la Kwes, jàppaleku sa.",
        evidence="Rendu exact ; relecture à 0,74 (« Manlaques ») : reconnaissance approximative.",
    ),
    VoiceLanguage(
        code="tw",
        label="Akan (Twi)",
        family="prioritaire",
        status=STATUS_EXPERIMENTAL,
        asr=False,
        tts=True,
        phrase="Maakye, me ne Kwes, wo boafo.",
        evidence="Audio produit (2,7 s) mais aucune transcription restituée : reconnaissance non exploitable.",
    ),
    VoiceLanguage(
        code="bci",
        label="Baoulé",
        family="côte d'ivoire",
        status=STATUS_EXPERIMENTAL,
        asr=False,
        tts=True,
        phrase=None,
        evidence="Phrase générée par le modèle (« N n ti Kwes… ») ; relecture inexploitable (entendu « 25 de julio »).",
    ),
    VoiceLanguage(
        code="dyu",
        label="Dioula",
        family="côte d'ivoire",
        status=STATUS_EXPERIMENTAL,
        asr=False,
        tts=True,
        phrase=None,
        evidence="Phrase générée par le modèle (« I ni cé, ne bɛ Kwes… ») ; relecture partielle (0,63).",
    ),
    VoiceLanguage(
        code="bet",
        label="Bété",
        family="côte d'ivoire",
        status=STATUS_EXPERIMENTAL,
        asr=False,
        tts=True,
        phrase=None,
        evidence="Phrase générée par le modèle, mélangée au français (« … o gba assistant personnel ») ; relecture 0,74.",
    ),
    VoiceLanguage(
        code="nouchi",
        label="Nouchi",
        family="côte d'ivoire",
        status=STATUS_EXPERIMENTAL,
        asr=True,
        tts=True,
        phrase=None,
        evidence="Fonctionne (base française) ; relecture à 0,99, le nom ressort « Kwess » avec le /s/ final.",
    ),
)

_BY_CODE = {language.code: language for language in LANGUAGES}


def list_languages() -> list[dict[str, Any]]:
    return [language.as_dict() for language in LANGUAGES]


def resolve(code: str | None) -> VoiceLanguage | None:
    if not code:
        return None
    return _BY_CODE.get(code.strip().lower())


def prompt_hint(code: str | None) -> str | None:
    """Consigne de langue injectée dans le prompt vocal (jamais une traduction)."""
    language = resolve(code)
    if language is None:
        return None
    if language.status == STATUS_UNAVAILABLE:
        return None
    return (
        f"Langue de la conversation : {language.label} ({language.code}). "
        "Réponds dans cette langue, sans mélanger, sauf si la personne change de langue."
    )

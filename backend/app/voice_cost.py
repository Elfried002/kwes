"""Coût estimé d'une session vocale Gemini (jamais présenté comme une facture).

Tarifs publiés au 16/11/2026 pour `gemini-3.8-live`, palier payant, en dollars
par minute d'audio :
- entrée audio  : 0,005 $/min ;
- sortie audio : 0,018 $/min.

Le palier gratuit existe mais réutilise les données pour améliorer les produits ;
on ne peut pas déduire le palier depuis l'API, donc on affiche une estimation au
tarif payant et on le dit.
"""

from __future__ import annotations

from dataclasses import dataclass

USD_PER_MIN_INPUT = 0.005
USD_PER_MIN_OUTPUT = 0.018
# Taux indicatif : le coût réel dépend du taux appliqué par la banque.
USD_TO_EUR = 0.92


@dataclass(frozen=True)
class Estimate:
    usd: float
    eur: float
    minutes_in: float
    minutes_out: float

    def as_dict(self) -> dict[str, float]:
        return {
            "estimated_usd": round(self.usd, 4),
            "estimated_eur": round(self.eur, 4),
            "minutes_in": round(self.minutes_in, 2),
            "minutes_out": round(self.minutes_out, 2),
        }


def estimate(audio_in_seconds: float, audio_out_seconds: float) -> Estimate:
    minutes_in = max(0.0, audio_in_seconds) / 60
    minutes_out = max(0.0, audio_out_seconds) / 60
    usd = minutes_in * USD_PER_MIN_INPUT + minutes_out * USD_PER_MIN_OUTPUT
    return Estimate(
        usd=round(usd, 6),
        eur=round(usd * USD_TO_EUR, 6),
        minutes_in=minutes_in,
        minutes_out=minutes_out,
    )

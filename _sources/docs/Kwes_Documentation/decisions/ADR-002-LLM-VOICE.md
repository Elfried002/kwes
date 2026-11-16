# ADR-002 — DeepSeek et ElevenLabs

- **Statut :** accepté sous réserve de validation fournisseur
- **Date :** 2026-11-15

## Décision
DeepSeek est le fournisseur initial de raisonnement. ElevenLabs Speech Engine est la voie vocale initiale envisagée.

## Règle
Le backend orchestre la conversation et les outils. La voix est isolée derrière une interface `VoiceProvider`.

## Réserve
Confirmer le mode exact ElevenLabs, ses API, son SDK, la compatibilité LLM externe et ses langues avant implémentation. Ne pas mélanger Speech Engine, ElevenAgents et Eleven Realtime.

## Conséquence
Le système reste remplaçable et peut basculer en texte si la voix est indisponible.

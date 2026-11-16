# Risques, hypothèses et dépendances — Kwes

| Risque | Impact | Réduction |
|---|---|---|
| Achat VPS tardif | Retard déploiement | Préparer localement en parallèle |
| Clés fournisseurs indisponibles | Voix/LLM bloqués | Tester accès le premier jour |
| API ElevenLabs différente du mode attendu | Intégration vocale retardée | Vérifier produit, SDK et protocole avant coder |
| Budget 4 vCPU/8 Go insuffisant | Workers instables | Limiter concurrence et Playwright |
| CORS/WebSocket | Frontend déconnecté | Test de connectivité dès jour 1 |
| Langues locales non supportées | Promesse non tenue | Afficher niveaux de support et plan d'évaluation |
| Prompt injection | Action malveillante | Policy Engine et données non fiables |
| Tâche doublonnée | Effet externe répété | Idempotence et vérification |
| Temps limité | Démo incomplète | Prioriser le parcours central |
| Dépendance à un fournisseur | Indisponibilité | Adaptateurs et fallback texte |

## Dépendances externes à vérifier

- documentation et accès API DeepSeek ;
- offre, modèle et mode exacts ElevenLabs ;
- langues ASR/TTS actuellement supportées ;
- quotas et tarifs fournisseurs ;
- restrictions géographiques téléphonie si intégrée ;
- limites Vercel et Supabase selon l'offre ;
- politique de sauvegarde VPS.

## Règle de gestion

Aucune fonctionnalité ne doit être déclarée livrée sur la base d'une maquette ou d'une réponse simulée. La démonstration doit identifier clairement les fonctions réelles, expérimentales et prévues.

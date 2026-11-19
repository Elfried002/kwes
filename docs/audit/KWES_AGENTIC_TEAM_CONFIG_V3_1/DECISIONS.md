# Décisions d’architecture retenues

1. KWES est universel, business/productivité orienté résultats et compagnon du quotidien.
2. KWES Core est le chef d’orchestre central.
3. Chaque spécialiste est un agent à part entière et possède `config.yaml`, `SOUL.md`, `AGENT.md`, `AGENT_SPEC.md`.
4. 16 agents spécialisés sont définis dès le départ ; sélection dynamique selon la mission.
5. Coordination entre spécialistes uniquement via Core/Task Orchestrator.
6. Exécution parallèle lorsque les tâches sont indépendantes ; limites de concurrence, temps et coûts.
7. Le Policy Engine backend impose les autorisations ; un prompt ne constitue jamais une barrière de sécurité suffisante.
8. Les livrables sont attachés à la conversation et à la mission depuis un stockage commun sécurisé.
9. Supabase reste la source de vérité persistante ; Supabase Storage conserve les fichiers.
10. Les modèles restent limités à ceux autorisés dans le référentiel, sans fallback non approuvé.
11. Ce package est une définition d’architecture, pas une preuve de déploiement ou de disponibilité des connecteurs.

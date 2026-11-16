# Journal des décisions techniques — Kwes

## D-001 — Monorepo unique (`business/kwes`)
Frontend, backend, base et infra dans un seul dépôt, lots séparés par répertoire. Raison : un seul propriétaire par dossier, pas de conflit entre sous-agents, intégration simple.

## D-002 — SQLAlchemy 2 async + psycopg3 (pas de supabase-py côté backend)
Le backend parle directement à PostgreSQL. Raison : migrations SQL réutilisables telles quelles sur Supabase, tests locaux possibles sans service distant. Les RLS restent écrites pour l'accès client Supabase.

## D-003 — SQLite pour les tests unitaires, PostgreSQL pour l'exécution
Les tests doivent tourner sans Postgres. Limite assumée : les RLS et pgvector ne sont pas couverts par ces tests, seulement par les migrations et la vérification SQL.

## D-004 — JWT HS256 en dev, Supabase JWT en production
Même code de vérification, secret différent. Aucun contournement d'authentification en production.

## D-005 — Mocks explicites pour les fournisseurs IA
Sans clé, DeepSeek et ElevenLabs basculent en mock déterministe marqué (`X-Kwes-Mock: 1` + log warning). Un mock n'est jamais présenté comme une intégration réelle.

## D-006 — Policy engine en code, hors du LLM
Niveaux R0–R4, décision allow / deny / approval, journalisée dans `audit_logs`. Le modèle propose, le code décide.

## D-007 — Orb en Canvas/SVG + machine à états, pas le GIF
Le GIF du pack est un asset de communication. L'interface utilise une animation pilotée par les événements réels, avec fallback statique si `prefers-reduced-motion`.

## D-008 — Aucun déploiement distant aujourd'hui
VPS, Vercel et Supabase restent préparés, non exécutés : pas d'accès, pas de dépense autorisée.

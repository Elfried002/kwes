# IMPLEMENTATION_STATUS — Kwes

Mis à jour : 16/11/2026 07:30 · branche `alpha/jour-1` · commit `0a1480e`
Statuts : NOT_STARTED · IN_PROGRESS · IMPLEMENTED · TESTED · BLOCKED · DEFERRED

## Ce qui tourne réellement aujourd'hui

| Brique | Statut | Preuve |
|---|---|---|
| Backend FastAPI | TESTED | 116 tests pytest passés |
| PostgreSQL 16 + pgvector | TESTED | 13 tables, 13/13 RLS, 33 policies, 3 skills seedés |
| Redis 7 | TESTED | healthy, utilisé comme file de tâches |
| Worker | TESTED | mission exécutée : 2 étapes, 2 skills, `completed` 100 % |
| DeepSeek (clé réelle) | TESTED | réponse réelle en français, `X-Kwes-Mock` absent |
| Frontend React/TS | TESTED | tsc exit 0, 43 tests Vitest, build 318 kB |
| Interface ↔ API | TESTED | login `/dev/token`, chat réel affiché, WS connecté |
| Migrations SQL | TESTED | appliquées sur PostgreSQL réel, idempotentes |
| ElevenLabs | IMPLEMENTED non testé | clé validée (/v1/voices ok), aucune synthèse jouée |
| Orb | TESTED | 34 tests transitions + rendu canvas vérifié |
| Docker compose | TESTED partiellement | postgres+redis ; backend/worker/proxy non testés ensemble |
| CI GitHub Actions | IMPLEMENTED non exécuté | actionlint OK, jamais lancé |
| Vercel / Supabase distant / VPS | BLOCKED | aucun accès, aucune dépense |

## Fonctionnalités Alpha
FR-001 TESTED · FR-002 TESTED · FR-003 TESTED (9 conversations, 27 messages) · FR-004 TESTED ·
FR-005 TESTED (5 tâches, 10 étapes) · FR-006 TESTED · FR-007 TESTED · FR-008 TESTED (9 audit_logs, 5 executions) ·
FR-009 TESTED en tests (R2 → awaiting_approval), 0 approbation réelle · FR-010 BLOCKED · FR-011 NOT_STARTED ·
FR-012 NOT_STARTED · FR-013 IMPLEMENTED non testé · FR-014 NOT_STARTED · FR-015 IMPLEMENTED · FR-016 NOT_STARTED

## Commandes et résultats
```
cd backend && python -m pytest -q          → 116 passed, 0 failed (34 s)
cd frontend && npx tsc --noEmit            → exit 0
cd frontend && npx vitest run              → 43 passed / 43
cd frontend && npm run build               → built in 2.8 s
cd backend && python tests/e2e_check.py    → mission completed 100 %
```

## Bugs d'intégration trouvés et corrigés
1. `tasks.priority` integer vs texte → migration 0004
2. `task_steps.depends_on` uuid[] vs clés d'étape → migration 0005
3. `audit_logs.actor_type` refusait `agent` → migration 0006
4. `audit_logs.decision` en majuscules → normalisation
5. `business_planning.constraints` chaîne vs tableau → schéma tolérant + normalisation
6. Profil absent (FK auth.users) → route `/dev/token` réutilisant l'identité par e-mail

## Blocages
1. Aucun Supabase distant · 2. Aucun VPS/domaine · 3. Vercel non authentifié ·
| Playwright installé et branché (rendu Chromium) · 5. worker in-process

## Mise à jour 16/11 07:00 — Playwright et Supabase
- Playwright 1.56 + Chromium headless installés, `app/skills/render.py` ajouté, `make_browser_fetcher` branché à la place de `make_fetcher`.
- Preuve de rendu JS : page `quotes.toscrape.com/js` → **10 citations rendues** via Chromium contre **0** via httpx.
- Garde-fous vérifiés : `127.0.0.1` refusé (port), `169.254.169.254` refusé (metadata), domaine hors allowlist refusé.
- Suite complète : 116 tests passent après intégration. Mission réelle rejouée : `completed 100 %` avec log `render ok ... ms=2597`.
- Supabase : projet `kwes` (ref `yhgbvyibsvsjpxsnjdzn`, eu-west-2, PG 17.11) lié. 6 migrations prêtes, `db push --dry-run` OK — **poussée en production en attente d'accord explicite**.

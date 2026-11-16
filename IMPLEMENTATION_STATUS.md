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

## Déploiement réel 16/11 07:05
- **Supabase** : 6 migrations appliquées en production (`db push --remote --yes`), 13 tables créées, 3 skills + 3 versions seedés. Correctif 0004 rendu conditionnel (double définition de `priority` selon la version de 0001).
- **Vercel** : frontend déployé → https://frontend-phi-pied-lzumzbngjw.vercel.app
- **API** exposée temporairement en HTTPS sur `https://n8n.streetflexs.store/kwes-api/api/v1` (nginx → 127.0.0.1:8000), WebSocket compris. `DEV_ENDPOINTS=false` : plus aucune création de jeton anonyme.
- **Bout en bout vérifié depuis l'extérieur** : app Vercel → API HTTPS → DeepSeek → réponse affichée. Message « Quel jour sommes-nous ? » → « lundi 16 novembre 2026 » après injection de la date serveur.
- **Bug corrigé** : le modèle hallucinait la date (réponse « lundi 20 avril 2026 ») faute de contexte temporel → date UTC injectée dans le prompt système.

## Mise à jour 16/11 07:00 — Playwright et Supabase
- Playwright 1.56 + Chromium headless installés, `app/skills/render.py` ajouté, `make_browser_fetcher` branché à la place de `make_fetcher`.
- Preuve de rendu JS : page `quotes.toscrape.com/js` → **10 citations rendues** via Chromium contre **0** via httpx.
- Garde-fous vérifiés : `127.0.0.1` refusé (port), `169.254.169.254` refusé (metadata), domaine hors allowlist refusé.
- Suite complète : 116 tests passent après intégration. Mission réelle rejouée : `completed 100 %` avec log `render ok ... ms=2597`.
- Supabase : projet `kwes` (ref `yhgbvyibsvsjpxsnjdzn`, eu-west-2, PG 17.11) lié. 6 migrations prêtes, `db push --dry-run` OK — **poussée en production en attente d'accord explicite**.


## Mise à jour 16/11 20:45 — capacité agentique (déployée)

**Ce qui change pour l'utilisateur** : Kwes agit dans la conversation au lieu de répondre
« je ne peux pas ». Il cherche sur le web, lit une page, retient un fait durable et rédige un
document téléchargeable depuis la réponse.

| Brique | Statut | Preuve |
|---|---|---|
| Boucle d'outils conversationnelle (2 tours max, 3 appels/tour) | TESTED + PROD | LLM réel : `remember` ×2 en un tour, via HTTPS public |
| Classification d'intention à 3 voies (direct / outil / mission) | TESTED | `Intention` + repli heuristique ; `mode:"outil"` forcé pour les tests |
| Policy engine par appel d'outil + audit `chat.tool.call` | TESTED | `test_tools.py` : refus hors périmètre, décision `allow` journalisée |
| Skill `remember` (mémoire persistante, dédoublonnage) | TESTED + PROD | ligne créée en PostgreSQL réel, puis réinjectée dans le prompt |
| Skill `document_write` + table `documents` + API privée | TESTED + PROD | note de 909 car. téléchargée depuis Chrome (Playwright) |
| Pastille « ouvrir le document » dans la conversation | TESTED + PROD | capture `.review/chat-document-1440x900.png`, téléchargement réel |
| PWA installée → connexion directe | TESTED + PROD | mode standalone émulé : écran de connexion, pas la page publique |

**Correctifs d'intégration trouvés par l'exécution réelle**
1. `memories.source_id` déclaré `String` alors que la colonne est `uuid` → première écriture mémoire en échec (`DatatypeMismatch`). Modèle corrigé.
2. Contraintes `memories` (category/sensitivity) incompatibles avec le vocabulaire de l'API → migration `0009`.
3. `skill_offline_mode` déclaré mais jamais appliqué : la suite de tests émettait de vraies requêtes HTTP (2 requêtes Wikipédia observées). Fetcher hors ligne ajouté + rebranchement du fetcher factice dans les tests.
4. `Content-Disposition` absent des en-têtes CORS exposés → le navigateur nommait le fichier `document.txt`.
5. `backend/.env` pointait la base sur `127.0.0.1:5432` alors que le service tourne sur le réseau Docker (`172.18.0.2`) : un redémarrage à l'aveugle aurait cassé l'API.

**Preuves du jour** : 153 tests backend · 134 tests frontend · `tsc` exit 0 · build Vite OK ·
bundle de production vérifié (`turn__document`, `standalone`) · appels réels sur
`https://n8n.streetflexs.store/kwes-api/api/v1` avec la session Supabase de démonstration.

**Limites assumées**
- `web_research` dépend de DuckDuckGo (Instant Answer) et de Wikipédia : sur une requête
  d'actualité ou commerciale, il peut renvoyer 0 source. Un vrai moteur de recherche demande
  une clé payante (décision d'Elfried).
- Les domaines hors allowlist sont refusés par la politique (ex. `payoneer.com`) : c'est le
  comportement voulu, annoncé au modèle, qui le dit à l'utilisateur.
- Aucun envoi d'e-mail, aucune action R2 depuis la conversation (approbation requise).
- Upload de fichiers par l'utilisateur non branché (le bouton « Joindre » existe côté UI).

# KWES — Contrat d'intégration (source de vérité pour les lots)

Version 1 · 16/11/2026 · Référence : `docs/07-api/API_CONTRACTS.md`, `docs/06-data/DATA_MODEL.md`

## Ports et URLs
- Backend local : `http://127.0.0.1:8000`, préfixe `/api/v1`, health sur `/api/v1/health` **et** `/health`.
- Frontend local : `http://127.0.0.1:5173`, variable `VITE_API_BASE_URL`.
- WS : `/api/v1/ws?token=<jwt>`.

## Authentification
- `Authorization: Bearer <jwt>` sur toutes les routes privées.
- Dev : JWT HS256 signé avec `DEV_JWT_SECRET` (défaut `dev-secret-change-me`), claims `sub` (user_id UUID), `email`, `exp`.
- Prod : Supabase JWT vérifié via `SUPABASE_JWT_SECRET` (HS256) — même code, secret différent.
- Le backend crée automatiquement le profil s'il n'existe pas (dev/demo).

## Erreurs
```json
{"error":{"code":"STRING_CODE","message":"message lisible","details":{}}}
```
Codes : `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`, `PROVIDER_UNAVAILABLE`, `RATE_LIMITED`, `APPROVAL_REQUIRED`, `INTERNAL`.

## Endpoints (P0)
- `GET /api/v1/health` → `{status, version, dependencies:{database,redis,llm}}`
- `POST /api/v1/chat` → `{conversation_id, message_id, response, task_id?, status}`
- `GET|POST /api/v1/conversations`, `GET|DELETE /api/v1/conversations/{id}`
- `GET /api/v1/conversations/{id}/messages`
- `POST|GET /api/v1/tasks`, `GET /api/v1/tasks/{id}`, `POST /api/v1/tasks/{id}/{cancel|pause|resume}`
- `GET /api/v1/skills`, `GET /api/v1/skills/{id}`
- `GET /api/v1/memory`, `PATCH|DELETE /api/v1/memory/{id}`
- `GET /api/v1/approvals`, `POST /api/v1/approvals/{id}/{approve|reject}`
- `GET /api/v1/notifications`

## Événements WebSocket (serveur → client)
`conversation.delta`, `conversation.completed`, `task.created`, `task.updated`, `task.step.started`, `task.step.completed`, `task.awaiting_approval`, `task.failed`, `notification.created`, `system.status`.

Enveloppe :
```json
{"event":"task.updated","event_id":"uuid","timestamp":"ISO8601Z","data":{}}
```

## Mapping événements → états de l'Orb (frontend)
| Source | État Orb |
|---|---|
| rien en cours | `idle` |
| micro actif (client) | `listening` |
| `POST /chat` en vol | `thinking` |
| `task.updated` status=running, ou `task.step.started` | `executing` |
| `task.awaiting_approval` | `waiting_approval` |
| réponse assistant affichée | `response` |
| `task.updated` status=completed | `success` (2 s puis `idle`) |
| `task.failed` / erreur API | `error` |
| audio en lecture | `speaking` |

L'état ne doit jamais être déduit du texte du LLM.

## Base de données (PostgreSQL 15+)
Tables : `profiles, conversations, messages, tasks, task_steps, executions, skills, skill_versions, memories, approvals, integrations, audit_logs, notifications` — colonnes conformes à `docs/06-data/DATA_MODEL.md`, UUID en PK, `user_id` sur les données privées, timestamps UTC (`timestamptz`).

Statuts task : `queued, planning, awaiting_approval, running, paused, completed, failed, cancelled`.
Statuts step : `pending, ready, running, awaiting_approval, completed, failed, skipped`.

## Règles non négociables
1. Aucun secret dans le frontend ni dans Git ; `.env.example` sans valeurs.
2. Le policy engine est du code, jamais une décision du LLM.
3. Aucune action `success` sans confirmation d'exécution réelle.
4. Mocks autorisés seulement pour DeepSeek/ElevenLabs si les clés sont absentes — et signalés comme tels (`X-Kwes-Mock: 1`, log explicite).
5. Toute donnée de démo est marquée `is_demo` ou préfixée `[DEMO]`.

## Variables d'environnement
```
DATABASE_URL=postgresql+psycopg://kwes:kwes@127.0.0.1:5432/kwes
REDIS_URL=redis://127.0.0.1:6379/0
DEV_JWT_SECRET=dev-secret-change-me
SUPABASE_JWT_SECRET=
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

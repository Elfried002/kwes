# Kwes — Backend (FastAPI)

Implémentation du backend Alpha de Kwes : API `/api/v1`, authentification JWT,
orchestrateur agentique (DeepSeek + policy engine), worker asynchrone, skills et
diffusion temps réel. Contrat de référence : `../CONTRACTS.md` et
`../docs/07-api/API_CONTRACTS.md`.

## Lancement

```bash
cd backend
. .venv/bin/activate          # Python 3.14, dépendances dans requirements.txt
cp .env.example .env          # puis renseigner les valeurs utiles
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Sans `.env`, les valeurs de développement du contrat s'appliquent
(`DEV_JWT_SECRET=dev-secret-change-me`, PostgreSQL local, Redis local).

### Jeton de développement

```bash
python -c "import uuid; from app.core.security import create_dev_token; print(create_dev_token(uuid.uuid4(), 'demo@kwes.local'))"
```

Puis `Authorization: Bearer <token>` sur toutes les routes privées. Le profil est
créé automatiquement à la première requête.

## Routes (P0)

| Méthode | Route | Réponse |
|---|---|---|
| GET | `/health`, `/api/v1/health` | `{status, version, dependencies:{database,redis,llm}}` |
| POST | `/api/v1/chat` | `{conversation_id, message_id, response, status, intent, task_id?}` |
| GET/POST | `/api/v1/conversations` | liste / création |
| GET/DELETE | `/api/v1/conversations/{id}` | détail / suppression (204) |
| GET | `/api/v1/conversations/{id}/messages` | messages ordonnés |
| POST/GET | `/api/v1/tasks` | liste / création (201) |
| GET | `/api/v1/tasks/{id}` | mission + `steps` (input, output, risk déclaré) |
| POST | `/api/v1/tasks/{id}/(cancel\|pause\|resume)` | mission mise à jour |
| GET | `/api/v1/skills`, `/api/v1/skills/{id}` | catalogue (UUID ou nom) |
| GET | `/api/v1/memory` | mémoire de l'utilisateur (`category`, `q`) |
| PATCH/DELETE | `/api/v1/memory/{id}` | modification / suppression (204) |
| GET | `/api/v1/approvals` | approbations (`status`) |
| POST | `/api/v1/approvals/{id}/(approve\|reject)` | décision + mission |
| GET | `/api/v1/notifications` | notifications (`unread_only`) |
| POST | `/api/v1/voice/synthesize` | **additif** (hors P0) : ElevenLabs ou repli texte |
| WS | `/api/v1/ws?token=<jwt>` | événements du contrat |

Les collections sont renvoyées en **tableau JSON** avec `X-Total-Count` et
pagination `limit`/`offset`. Les erreurs suivent
`{"error":{code,message,details,request_id,retryable}}` et les codes du contrat.

## Mode MOCK explicite

Sans `DEEPSEEK_API_KEY` / `ELEVENLABS_API_KEY` :

- l'adaptateur DeepSeek produit des réponses **déterministes** (aucun appel
  réseau), suffixées `[MOCK] Réponse simulée — DEEPSEEK_API_KEY absente.` ;
- le VoiceProvider renvoie `fallback=true`, `audio_base64=null` et une raison ;
- chaque réponse HTTP porte `X-Kwes-Mock: 1` et `X-Kwes-Mock-Providers: deepseek,elevenlabs` ;
- un `WARNING` est journalisé au démarrage et à chaque appel simulé.

Avec les clés, les appels réels utilisent `/chat/completions` (timeout, retries
bornés sur 429/5xx) et `/v1/text-to-speech/{voice_id}` (repli texte si échec).
Aucune clé n'est codée en dur et `.env` n'est jamais versionné.

## Orchestrateur et policy engine

Chaîne : message → classification d'intention → plan JSON strict (Pydantic +
validation des skills/dépendances/limites) → autorisation par le **policy
engine** (code, jamais le LLM) → exécution par le worker → vérification →
rapport final.

| Niveau | Exemples | Décision |
|---|---|---|
| R0 | recherche web, lecture de page | autorisé si domaine allowlisté |
| R1 | plan local, brouillon | autorisé |
| R2 | publication/envoi externe | **approbation requise** (hash de charge utile + expiration + anti-replay) |
| R3 | paiement, contrat | refusé dans l'Alpha |
| R4 | contournement, exfiltration, suppression d'audit | refusé |

Le risque effectif = maximum(politique codée du skill, drapeaux de l'entrée,
risque déclaré par le LLM). Un LLM qui déclare `R0` sur une publication obtient
quand même une demande d'approbation. Chaque décision est journalisée dans
`audit_logs` (données expurgées).

Une mission ne passe à `completed` qu'après persistance d'une ligne
`executions` en statut `completed` **et** d'une sortie non vide pour chaque
étape ; sinon `failed` avec `EXECUTION_UNVERIFIED`.

## Worker et file

- File Redis (`kwes:queue:tasks`) si disponible, sinon file in-process
  (mono-instance, non persistante) — `QUEUE_BACKEND=auto|redis|memory`.
- Heartbeat périodique, `concurrency` configurable, reprise des tâches
  orphelines (`queued`, `planning`/`running` plus vieilles que le TTL) au
  démarrage, retries avec backoff exponentiel borné, persistance des exécutions.

## Skills

`app/skills/<nom>/` : `manifest.yaml`, `schemas/input.json`,
`schemas/output.json`, `skill.py`. Le registre vérifie à l'exécution : version
active, schéma d'entrée, permissions déclarées ⊆ permissions autorisées par
code, timeout, schéma de sortie. Un manifeste ne peut pas élargir ses droits
(`secrets.read` → skill refusé au chargement), ni abaisser son niveau de risque.

| Skill | Risque | Entrée | Sortie |
|---|---|---|---|
| `web_research` | R0 | `query`, `scope?`, `depth?` | `sources`, `facts`, `synthesis`, `limits` |
| `business_planning` | R1 | `objective`, `context?`, `constraints?` | `steps`, `risks`, `kpis`, `external_action` |
| `browser_readonly` | R0 | `url`, `objective?` | `title`, `content`, `links`, `injection_detected` |

Sécurité réseau : http/https uniquement, ports 80/443, pas d'identifiants dans
l'URL, allowlist de domaines (`BROWSER_ALLOWLIST`), blocage localhost/IP
privées/link-local/metadata cloud, DNS revérifié à chaque redirection.
Le contenu lu est traité comme non fiable : les lignes d'injection sont
neutralisées (`[CONTENU NON FIABLE SUPPRIMÉ]`) et signalées, jamais exécutées.

## WebSocket

`GET /api/v1/ws?token=<jwt>` → `system.status` initial, heartbeat périodique,
`ping` texte → `system.status {pong:true}`. Origin vérifiée (liste CORS ; en
prod `WS_REQUIRE_ORIGIN=true` rend l'en-tête obligatoire), rate limit par
utilisateur. Événements diffusés dans l'enveloppe du contrat
(`event`, `event_id`, `timestamp`, `data`) : `conversation.delta`,
`conversation.completed`, `task.created`, `task.updated`,
`task.step.started`, `task.step.completed`, `task.awaiting_approval`,
`task.failed`, `notification.created`, `system.status`. Le WS n'est pas une
source de vérité : resynchronisation REST après reconnexion.

## Tests

```bash
. .venv/bin/activate
python -m pytest
```

État de référence : **116 passed** (~32 s) sur 11 fichiers — auth, health, chat,
conversations, tâches, policy, skills, planificateur, approbations, isolation,
WS, infra.
Aucun accès réseau n'est effectué : un fetcher factice est injecté dans
`app.state.fetcher` / `orchestrator.fetcher`.

### Limites assumées

- **SQLite (aiosqlite) en test** : PostgreSQL n'est pas disponible dans
  l'environnement. Types natifs PG (`uuid`, `jsonb`, `timestamptz`), RLS,
  index GIN/pgvector et contraintes d'exclusion ne sont donc pas exercés. Le
  schéma SQLAlchemy cible PostgreSQL 15+ et `DATABASE_URL` bascule sans
  changement de code (`postgresql+psycopg://`).
- **Redis absent en test** : file in-process, heartbeat en mémoire ; la branche
  Redis est codée mais non exercée ici.
- **Playwright indisponible** : `browser_readonly` utilise httpx + extraction
  HTML lisible (pas de rendu JavaScript). Le contrat de sécurité (allowlist,
  anti-SSRF, contenu non fiable) est identique ; un rendu JS nécessiterait
  l'installation de Playwright et un navigateur isolé.
- **Recherche web** : `web_research` interroge l'API publique DuckDuckGo
  (sans clé) puis, si elle ne renvoie rien, l'API de recherche Wikipédia
  (domaines allowlistés). Seuls les domaines de l'allowlist sont lus ; sans
  réseau, le skill échoue proprement (`PROVIDER_UNAVAILABLE`) au lieu
  d'inventer des sources.
- **Rate limiting** en mémoire : suffisant pour une instance Alpha, à remplacer
  par Redis en multi-instance.
- **Annulation/pause** : signaux en mémoire + statut en base ; en multi-instance
  il faudrait un canal partagé (Redis) pour interrompre un worker distant.

## Arborescence

```
app/
  main.py            # app factory, lifespan, CORS, erreurs, health
  ws.py              # WebSocket authentifié + diffusion
  core/              # config, sécurité, erreurs, events, rate limit, middleware
  db/                # engine async, session, 13 modèles ORM
  api/               # routes P0 + sérialiseurs
  agent/             # orchestrateur, planner, policy engine, DeepSeek, voix, audit
  skills/            # registre + web_research, business_planning, browser_readonly
  worker/            # file (Redis/mémoire) + worker (heartbeat, retries, orphelines)
tests/               # pytest (SQLite, fetcher factice, aucun réseau)
```

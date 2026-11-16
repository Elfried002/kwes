# KWES — Rapport d'implémentation P0

**Phase** : P0 — préparation technique, isolation du worker, sécurisation du socle
**Date** : 16 novembre 2026, 22 h 30 · **Commit de référence avant travaux** : `9405f52`
**Sauvegarde** : `/home/babayaga/backups/kwes-pre-p0-20261116-2205.tgz` (509 Ko, `backend/` + `supabase/`)
**Statut global** : toutes les exigences P0 vérifiées en exécution réelle. Aucune régression.

P1, P2, P3, P4, P5, P6 n'ont pas été commencées.

---

## 1. Résumé

Le worker de missions ne tourne plus dans le processus de l'API. Deux services systemd
indépendants (`kwes-api`, `kwes-worker`) partagent la même base PostgreSQL et la même file Redis.
La logique métier n'a pas été réécrite : elle est appelée par une fabrique commune
(`app/worker/runtime.py`, qui réutilise `build_orchestrator`).

Ce qui a changé concrètement :

| Avant | Après |
|---|---|
| Worker dans le processus uvicorn | Service `kwes-worker` séparé |
| File Redis en `BRPOP` (perte de l'élément en cas de crash) | `BLMOVE` vers une liste « en cours » + acquittement |
| Aucun verrou : deux workers pouvaient exécuter la même tâche | Verrou PostgreSQL `tasks.claimed_by` (UPDATE atomique) |
| Reprise uniquement au démarrage | Reprise au démarrage **et** balayage périodique (30 s) |
| `Redis` indisponible → HTTP 500 à la création de mission | Mission créée (201), reprise automatique ensuite |
| Aucune procédure d'exploitation | Unités systemd, arrêt propre, supervision, rollback documenté |

**Garanties réellement obtenues** : *au moins une fois*, sans exécution simultanée.
**Pas** *exactement une fois* — voir §8.

---

## 2. Architecture

```
                     ┌──────────────────────────────┐
   Navigateur/PWA ──▶│ nginx (TLS, /kwes-api/)       │
                     └───────────────┬──────────────┘
                                     │ HTTP
                     ┌───────────────▼──────────────┐        ┌──────────────────┐
                     │ kwes-api.service             │        │ kwes-worker.svc  │
                     │ uvicorn :8000                │        │ python -m        │
                     │ • auth JWT (JWKS)            │        │   app.worker     │
                     │ • Policy Engine R0–R4        │        │ • BLMOVE/claim   │
                     │ • orchestrateur (chat)       │        │ • exécution      │
                     │ • WORKER_INLINE=false        │        │ • ack + verrou   │
                     └───────┬──────────────┬───────┘        └────┬─────────┬───┘
                             │              │                     │         │
                    ┌────────▼─────┐  ┌─────▼─────────────────────▼──┐  ┌───▼──────────┐
                    │ PostgreSQL   │  │ Redis (AOF, volume /data)    │  │ Chromium     │
                    │ source de    │  │ kwes:queue:tasks             │  │ (Playwright) │
                    │ vérité       │  │ kwes:queue:ids               │  │              │
                    │ tasks.claim  │  │ kwes:queue:processing:<id>   │  │              │
                    └──────────────┘  └──────────────────────────────┘  └──────────────┘
```

- L'API ne consomme plus la file (`WORKER_INLINE=false` dans l'unité).
- Le worker ne sert aucune requête HTTP : il ne peut donc pas exposer de surface d'attaque réseau.
- Les deux processus partagent la même fabrique de runtime ; aucune duplication de logique.
- Le Policy Engine reste appelé **dans le worker** pour chaque étape : le worker ne décide de rien.

## 3. Fichiers

**Créés**
| Fichier | Rôle |
|---|---|
| `backend/app/worker/__main__.py` | point d'entrée du service, signaux, `--check` |
| `backend/app/worker/runtime.py` | fabrique commune API/worker |
| `backend/app/worker/claims.py` | verrou d'exécution (claim/release/release_all) |
| `backend/app/skills/normalize.py` | normalisation des entrées (correctif de fiabilité) |
| `supabase/migrations/0011_task_claims.sql` | colonnes `claimed_by`, `claimed_at` (non destructif) |
| `deploy/systemd/kwes-api.service` | unité API |
| `deploy/systemd/kwes-worker.service` | unité worker |
| `backend/tests/test_worker_service.py` | 11 tests P0 |
| `backend/tests/test_normalize.py` | 4 tests de normalisation |
| `docs/CONTRATS_COMPETENCES.md` | contrats des six futures compétences |
| `docs/ROLLBACK_P0.md` | procédure de rollback |

**Modifiés**
| Fichier | Changement |
|---|---|
| `backend/app/worker/queue.py` | `BLMOVE` + liste en cours + acquittement + dédoublonnage |
| `backend/app/worker/worker.py` | claim, ack, arrêt propre avec drainage, balayage périodique |
| `backend/app/main.py` | worker inline conditionnel (`worker_inline`) |
| `backend/app/core/config.py` | `worker_inline`, `worker_drain_seconds`, `worker_claim_ttl_seconds`, `worker_sweep_interval_seconds`, `worker_name` |
| `backend/app/db/models.py` | `Task.claimed_by`, `Task.claimed_at` |
| `backend/app/agent/orchestrator.py` | `_enqueue` non bloquant (5 appels) |
| `backend/app/skills/registry.py` | normalisation avant validation |
| `backend/tests/conftest.py` | `worker_inline=True`, `browser_open_web=False` (tests hermétiques) |
| `backend/.env` | `BROWSER_OPEN_WEB=true` (décision produit validée) |

## 4. Services

| Unité | Utilisateur | Redémarrage | Arrêt | Limites | Journal |
|---|---|---|---|---|---|
| `kwes-api.service` | `babayaga` (non root) | `on-failure`, 3 s | SIGTERM, 40 s | `MemoryMax=2G`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, écriture limitée à `backend/` | journald |
| `kwes-worker.service` | `babayaga` (non root) | `always`, 5 s | SIGTERM, 25 s (drain 20 s) | idem | journald |

Configuration non sensible du worker : `QUEUE_BACKEND=redis`, `WORKER_NAME=kwes-worker-1`,
`KWES_ENV_FILE=backend/.env`. **Aucune valeur de secret dans les unités** : le fichier `.env`
reste la seule source, chargé par `EnvironmentFile`.

## 5. Exploitation

```bash
# État
systemctl status kwes-api kwes-worker
journalctl -u kwes-worker -f

# Démarrage / arrêt / redémarrage
sudo systemctl start   kwes-api kwes-worker
sudo systemctl stop    kwes-worker kwes-api
sudo systemctl restart kwes-worker          # sans impact sur l'API

# Santé du worker (battement de cœur Redis, sortie JSON, code 0/1)
sudo -u babayaga bash -lc 'cd /home/babayaga/business/kwes/backend && .venv/bin/python -m app.worker --check'

# File et verrous
sudo docker exec -i kwes-redis redis-cli llen kwes:queue:tasks
sudo docker exec -i kwes-postgres psql -U kwes -d kwes -c \
  "select status, count(*) from tasks group by status order by 2 desc;"
```

## 6. Rollback

Procédure complète : `docs/ROLLBACK_P0.md`. Résumé :

1. `sudo systemctl stop kwes-worker kwes-api`
2. Relancer l'API en mode historique (worker inline) :
   `cd backend && WORKER_INLINE=true .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`
3. `git revert <commit P0>` si nécessaire ; la migration `0011` est **additive** et peut rester
   (colonnes nullables, aucun code ne les lit en mode historique).

Aucune migration destructive n'a été appliquée.

## 7. Résultats des tests

| Test | Attendu | Résultat | Preuve |
|---|---|---|---|
| API démarre sans worker | `state.worker is None`, API 200 | **OK** | `test_api_starts_without_inline_worker`, `curl` 200 |
| Worker démarre sans API | service actif seul | **OK** | `systemctl start kwes-worker` (API arrêtée pendant la bascule) |
| Redémarrage worker ≠ API coupée | 10/10 réponses 200 | **OK** | 200 à 7,9–12,5 ms pendant `systemctl restart kwes-worker` |
| Mission soumise par l'API, exécutée par le worker | `completed` | **OK** | tâche `f44372db…`, 3 étapes, journal `Task … -> completed` |
| Résultats persistés | 3 étapes `completed` | **OK** | `select status,count(*) from task_steps` |
| Journaux exploitables | erreurs identifiables | **OK** | journald, `kwes.worker`, `kwes.queue`, `kwes.audit` |
| Arrêt propre | SIGTERM → sortie 0, tâche finie | **OK** | `Signal SIGTERM reçu` → `Worker arrêté (processed=1 failures=0)` |
| Reprise après arrêt brutal | tâche reprise | **OK** | `kill -9` à 25 % → « Reprise : 1 tâche(s) en cours » → `completed` en 17 s, 4 étapes |
| Pas de double exécution | 1 exécution malgré 3 entrées | **OK** | 2 refus « déjà détenue par un autre worker », 1 seule étape `completed` |
| Timeouts bornés | échec propre | **OK** | `test_policy`, `max_step_retries=1` en test, retries 3 en prod |
| Tâches échouées consultables | statut `failed` + code | **OK** | 6 tâches `failed` avec `error_code` (dont `FORBIDDEN`, `SKILL_VALIDATION`) |
| Redis indisponible | pas de perte | **OK** | POST 201 pendant coupure, mission `queued`, reprise par balayage, `completed` |
| Aucun secret dans les journaux | 0 occurrence | **OK** | `grep` sur 30 min de journald : 0 |
| Droits du worker | non root | **OK** | `User=babayaga`, `NoNewPrivileges=yes` |
| Isolation utilisateurs | RLS intacte | **OK** | 39 politiques, tests d'isolation verts |
| Policy Engine | toujours consulté | **OK** | `policy decision action=skill:…` dans le journal worker |
| Approbations hashées | inchangées | **OK** | `test_policy.py` vert, aucun code d'approbation modifié |
| **Backend** | 148 de référence | **163 verts** (+15) | `163 passed in 51.86s` |
| **Frontend** | 134 de référence | **134 verts** | `vitest run` |
| **Build frontend** | réussi | **OK** | `built in 4.79s` |
| API + HTTPS | répondent | **OK** | local 200, `https://n8n.streetflexs.store/kwes-api/api/v1/health` 200 |

Les 15 tests ajoutés : 11 dans `test_worker_service.py` (claim exclusif, TTL, reprise, drainage,
secrets, séparation API/worker) et 4 dans `test_normalize.py`.

## 8. Limites et risques restants

1. **Au moins une fois, pas exactement une fois.** Une étape interrompue entre son exécution et
   l'enregistrement de son résultat peut être rejouée. Les étapes `completed` ne sont jamais
   rejouées ; les actions sensibles restent derrière une approbation liée au hachage du payload.
   Les skills actuels sont R0/R1 et sans effet externe : le risque est nul aujourd'hui, il
   deviendra réel avec l'envoi d'e-mail (P6) — d'où la DLQ prévue en P5.
2. **Verrou à TTL de 120 s.** Un worker bloqué plus de 120 s sur une étape peut voir son verrou
   expiré ; un autre worker reprendrait alors la tâche. Les étapes sont courtes aujourd'hui
   (< 30 s), mais un OCR long (P3) exigera un renouvellement de verrou.
3. **Pas de Dead Letter Queue.** Une tâche qui échoue reste consultable en base (`failed`), mais
   aucune file de rebut n'existe encore. Prévu en P5.
4. **Un seul worker par défaut.** `kwes-worker.service` lance un processus avec
   `worker_concurrency=2`. Le multi-instance est supporté par le verrou mais pas encore outillé
   (pas d'unité `kwes-worker@.service`).
5. **`APP_ENV` non défini** dans `.env` → `dev`, donc les jetons HS256 de développement restent
   acceptés en production. Ce point touche l'authentification : **non modifié en P0**, à trancher.
6. **`BROWSER_OPEN_WEB=true`** activé conformément à ta décision. Les garde-fous SSRF restent
   actifs (vérifié : `127.0.0.1` et `169.254.169.254` refusés), mais la surface de lecture web
   s'élargit : chaque domaine lu reste journalisé.
7. **Mission `failed` pour `FORBIDDEN`** : certaines missions échouent encore parce que le plan
   cible un domaine bloqué par politique ou produit un `depth` non conforme. Le correctif de
   normalisation est en place ; le reste relève de P1 (qualité des plans).

## 9. Preuves techniques

```
$ systemctl is-active kwes-api kwes-worker
active
active

$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/health   → 200
$ curl -s -o /dev/null -w "%{http_code}" https://n8n.streetflexs.store/kwes-api/api/v1/health → 200

$ journalctl -u kwes-worker -o cat | tail
INFO kwes.queue File de tâches: Redis (worker=kwes-worker-1).
INFO kwes.runtime Runtime prêt (queue=redis, db=postgres, skills=5)
INFO kwes.worker Worker démarré (id=kwes-worker-1, concurrency=2, queue=redis)
INFO kwes.worker Task f44372db-… -> completed
WARNING kwes.queue Reprise : 1 tâche(s) en cours remise(s) en file.
INFO kwes.worker Task b078d69b-… -> completed
INFO kwes.worker Task 8e8a7bcf-… ignorée : déjà détenue par un autre worker.

$ docker exec kwes-postgres psql -U kwes -d kwes -c "\d tasks" | grep claimed
 claimed_by | text
 claimed_at | timestamp with time zone

$ docker exec kwes-redis redis-cli config get appendonly → appendonly yes
$ docker exec kwes-redis redis-cli llen kwes:queue:tasks → 0
$ pytest -q → 163 passed in 51.86s
$ npx vitest run → 134 passed
$ npm run build → built in 4.79s
```

## 10. Proposition de lancement de P1

P1 = recherche web à 0 FCFA. Périmètre proposé, sous réserve de ta validation :

1. **SearXNG auto-hébergé** en conteneur (aucun coût, aucune clé) + repli DuckDuckGo/Wikipédia.
2. **Extraction PDF** (`pypdf`, local, gratuit) pour les sources PDF.
3. **Registre de preuves** : table `evidence` (URL, titre, extrait, empreinte, date de lecture)
   pour que chaque affirmation d'une réponse soit rattachable à une source conservée.
4. **Quotas et cache** : compteur de requêtes par fournisseur, cache Redis par requête (TTL 24 h).
5. **Qualité des plans** : réduire les missions `failed` (normalisation étendue, validation du
   plan avant exécution, message d'erreur utile à l'utilisateur).

Risques P1 : SearXNG dépend d'instances publiques ou d'un déploiement local (images Docker,
~200 Mo, pas de coût) ; qualité variable des résultats ; respect des conditions des moteurs.

En attente de ta validation pour démarrer P1.

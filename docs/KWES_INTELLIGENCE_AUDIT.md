# KWES — Audit technique et préparation de Kwes Intelligence Suite v1.0

**Date** : 16 novembre 2026, 22 h 30 · **Nature** : audit en lecture seule · **Aucune modification de production**
Commit audité : `9405f52` (branche `alpha/jour-1`) · Package : `Kwes_Intelligence_Suite_v1.0.zip` (11 fichiers, 11,1 Ko)

---

## 1. Résumé exécutif

**Le point décisif de cet audit** : les sept « skills » du package ne sont pas des compétences de Kwes.
Ce sont des fichiers `SKILL.md` au format **Hermes** — des consignes de méthode lues par l'agent
Hermes (moi), pas du code exécutable par le backend Kwes. Les copier dans `~/.hermes/skills/`
apprendrait une méthode à l'agent d'exploitation ; cela **ne donnerait à Kwes ni fichiers, ni
e-mail, ni agenda, ni automatisations**. Le backend Kwes ne connaît que son propre registre
(`backend/app/skills/`), où chaque capacité = manifeste + code + schémas + politique + tests.

**État réel** : Kwes est solide sur son socle (API, politiques, missions, voix Gemini, mémoire,
documents produits par l'agent) et **absent** sur trois des six domaines visés : fichiers importés,
e-mail, agenda. Deux domaines sont partiels : recherche web (2 fournisseurs gratuits, pas de PDF,
pas de fournisseur à clé) et automatisations (worker durable mais **aucun ordonnanceur**).

**Conséquence** : le package est utilisable comme **spécification de comportement**, pas comme
implémentation. Le plan propose de le traduire en compétences Kwes réelles, dans l'ordre
recherche → mémoire → fichiers → agenda → e-mail → automatisations, avec un point d'arrêt et une
validation humaine à chaque étape.

**Aucun fichier de production, aucune configuration, aucune base, aucun service n'a été modifié
pendant cet audit.**

---

## 2. État technique de Kwes

### 2.1 Environnement

| Élément | Valeur mesurée | Preuve |
|---|---|---|
| Hermes | **v0.21.7+395.g386a9ea** (2026.9.24, stable, installation git) | `hermes --version` |
| Python (système et venv backend) | **3.14.7** | `python3 --version` |
| Répertoire de skills Hermes actif | `/home/babayaga/.hermes/skills` (profil `default`), arborescence par catégories | `find … -name SKILL.md` |
| Skills Hermes installés | **62** skills (business, research, productivity, web, etc.) | même commande |
| Répertoire des skills Kwes | `/home/babayaga/business/kwes/backend/app/skills` | `ls` |
| Skills Kwes (registre) | **5** : `web_research`, `browser_readonly`, `business_planning`, `remember`, `document_write` | `ls backend/app/skills` |
| Outils exposés en conversation | **4** : `web_research`, `browser_readonly`, `remember`, `document_write` | `CHAT_TOOL_NAMES`, `agent/tools.py:39` |

### 2.2 Dépendances principales (venv backend)

`fastapi 0.163.1` · `uvicorn 0.54.0` · `sqlalchemy 2.1.8` · `psycopg 3.3.9` · `pydantic 2.14.3` ·
`google-genai 3.3.0` · `playwright 1.65.2` (Chromium 159) · `httpx 0.28.1` · `redis 8.1.0` ·
`cryptography 50.0.2` · `jsonschema 4.26.0` · `pyyaml 6.0.3`.
**Absents** : `alembic`, `pypdf`, tout moteur d'OCR, tout SDK e-mail ou calendrier.

### 2.3 Exécution et services

| Composant | Réalité | Preuve |
|---|---|---|
| API | `uvicorn app.main:app` sur `127.0.0.1:8000`, exposée en HTTPS par nginx sous `/kwes-api/` | `ss -ltnp`, config nginx |
| Worker de tâches | **dans le même processus** que l'API (`TaskWorker` démarré au lifespan), file Redis, concurrence 2 | `app/main.py:137` |
| Base | PostgreSQL 17 dans le conteneur `kwes-postgres` (`172.18.0.2`), **17 tables**, **39 politiques RLS** | `docker ps`, `psql` |
| Cache/file | Redis 7 dans `kwes-redis` (`172.18.0.3`) | `docker ps` |
| Frontend | Vercel (SPA), alias `frontend-phi-pied-lzumzbngjw.vercel.app` | bundle vérifié |
| Ordonnanceur | **aucun** (aucune référence à APScheduler/cron dans le backend) | `grep` |
| Tests | **148** backend (verts, 45 s), **134** frontend | `pytest -q`, `vitest run` |

### 2.4 Authentification, stockage, journalisation

- **Auth** : JWT Supabase ES256 vérifié par JWKS mis en cache 10 min (`app/core/security.py`),
  HS256 en développement seulement. Le `user_id` vient du jeton, jamais du texte.
- **Stockage** : PostgreSQL uniquement. Les documents sont du **texte en base** (`documents.content`).
  Aucun Object Storage, aucun antivirus, aucun OCR.
- **Journalisation** : journal applicatif texte (`backend/api.log`) et table `audit_logs`
  (acteur, action, décision, ressource, métadonnées expurgées). Chaque appel d'outil, chaque
  décision de politique et chaque étape de mission y sont écrits.

### 2.5 Architecture actuelle

```
PWA (Vercel) → nginx/TLS → API FastAPI (auth → orchestrateur → policy engine → registre)
                                   │
                                   ├── Chat : intention direct/outil/mission
                                   ├── Outils : 4 skills autorisés, budget 2 tours / 3 appels
                                   ├── Missions : plan JSON validé → worker (file Redis) → étapes
                                   └── Voix : WebSocket ↔ Gemini Live (serveur à serveur)
```

---

## 3. Audit des six domaines fonctionnels

### 3.1 Recherche web — **PARTIEL**

| Point | Réalité | Preuve |
|---|---|---|
| Fournisseurs | **DuckDuckGo Instant Answer + Wikipédia** uniquement | `web_research/skill.py:28-30` |
| Extraction HTML | oui, textes/blocs/liens, neutralisation d'injections | `fetch.py:_Extractor` |
| Extraction PDF | **non** — aucun parseur installé | `import pypdf` → absent |
| Navigateur | Playwright/Chromium 159, rendu JS réel (preuves du 16/11) | `render ok … chars=1167984` |
| Citations | sources normalisées (URL, titre, extrait, statut), citées dans la réponse | `web_research/skill.py` |
| Profondeur | `quick=1`, `standard=3`, `deep=5` sources | `DEPTH_LIMIT` |
| SSRF | hôtes internes, IP privées/loopback/link-local, ports ≠ 80/443, redirections revalidées, résolution DNS | `fetch.py:30-115` |
| Injection de prompt | 7 motifs neutralisés, lignes remplacées par `[CONTENU NON FIABLE SUPPRIMÉ]` | `_INJECTION_PATTERNS` |
| Quotas / coûts | **aucun** quota par fournisseur ; seul le budget vocal est plafonné | `grep quota` |
| Fallback | DDG → Wikipédia ; échec signalé à l'utilisateur, jamais inventé | test réel du 16/11 (0 source annoncée) |
| Déduplication / tri qualité | **non** | code |
| Allowlist domaines | fermée en production (`BROWSER_OPEN_WEB=false`) : Wikipédia, example, DuckDuckGo | `config.py` |

**Verdict** : utilisable pour de la recherche documentaire simple ; insuffisant pour une recherche
commerciale fiable (0 source observé sur une requête réelle), et sans PDF.

### 3.2 Gestion des fichiers — **ABSENT** (avec un adjacent existant)

- Aucune route d'**import** : `documents` expose `GET /documents`, `GET /{id}`, `GET /{id}/download`,
  `DELETE /{id}` — **pas de POST**.
- Aucun stockage objet, aucun antivirus, aucune quarantaine, aucun OCR, aucun parseur PDF/DOCX/XLSX/PPTX.
- Ce qui **existe** : les documents **rédigés par l'agent** (skill `document_write`), stockés en
  texte, privés (RLS), téléchargeables depuis la conversation — 1 document réel créé et téléchargé.
- Le bouton « Joindre » existe dans l'interface mais **n'est relié à rien** côté API.

### 3.3 E-mail — **ABSENT**

Aucune référence à SMTP, IMAP, OAuth ou API de messagerie dans le backend (`grep` vide). La table
`integrations` existe mais aucun fournisseur n'est implémenté. Aucun scope OAuth, aucun brouillon,
aucune approbation liée à un hash de message.

### 3.4 Agenda — **ABSENT**

Aucune référence à un calendrier, à un fuseau stocké ou à un rappel. Les tâches Kwes ont des
horodatages mais aucun objet « événement ». Aucun connecteur.

### 3.5 Automatisations — **PARTIEL**

| Point | Réalité | Preuve |
|---|---|---|
| Exécution durable | tâches persistées (`tasks`, `task_steps`), file Redis, worker avec récupération des tâches orphelines | `worker.py`, `test_infra` |
| Étapes, dépendances | plan JSON validé, 6 étapes max, dépendances ordonnées | `planner.py` |
| Pause / reprise / annulation | routes dédiées et signaux en mémoire | `api/tasks.py` |
| Retries / timeout | retries bornés + backoff + timeout par skill | `orchestrator._run_skill` |
| Historique | `executions` (statut, durée, erreur) et `audit_logs` | tables |
| **Déclencheurs** | **aucun** : pas de planification horaire, pas de webhook, pas de seuil | `grep scheduler/cron` vide |
| **Dead-letter queue** | **aucune** | code |
| Idempotence | clé d'idempotence par exécution, mais pas de garantie de non-double-effet externe | `idempotency_key` |
| Isolation | worker **dans le processus API** : une tâche OCR/navigateur lourde bloquerait l'API | `main.py` |

### 3.6 Mémoire intelligente — **PARTIEL**

| Point | Réalité | Preuve |
|---|---|---|
| Mémoire durable | table `memories`, écriture par l'outil `remember`, dédoublonnage sur contenu exact | `skills/remember/skill.py` |
| Isolation | `user_id` obligatoire + RLS | schéma + tests |
| Injection | 12 derniers faits injectés dans le prompt (ordre chronologique inverse) | `orchestrator._load_memories` |
| Provenance | `source_type`, `confidence`, `sensitivity`, `expires_at` stockés | modèle |
| **Embeddings** | **aucun** code d'embedding | `grep embedding` vide |
| **Recherche sémantique** | **aucune** — la colonne `pgvector` existe mais n'est jamais alimentée ni interrogée | code |
| Expiration | champ présent, **jamais appliqué** au retrieval | code |
| Consentement / sensibilité | niveaux stockés, **aucun traitement différencié** | code |

---

## 4. Matrice de maturité

| Capacité | État | Justification | Preuve |
|---|---|---|---|
| Socle API + auth + RLS | **EXISTANT** | 148 tests, 39 politiques RLS, JWKS ES256 | `pytest`, `pg_policies` |
| Policy Engine R0–R4 + approbations | **EXISTANT** | 14 tests dédiés, audit par décision | `test_policy.py` |
| Missions (plan, worker, reprise) | **EXISTANT** | mission réelle jouée, pause/reprise | `test_tasks.py` |
| Voix Gemini Live | **EXISTANT** | session réelle, audio joué, coût suivi | `voice_sessions`, tests du 16/11 |
| Recherche web | **PARTIEL** | 2 fournisseurs gratuits, pas de PDF, pas de quotas | §3.1 |
| Lecture de page / navigateur | **EXISTANT** | Chromium, rendu JS, SSRF | `render ok`, tests |
| Fichiers importés | **ABSENT** | aucun POST, aucun parseur, aucun stockage objet | §3.2 |
| E-mail | **ABSENT** | aucune ligne de code | §3.3 |
| Agenda | **ABSENT** | aucune ligne de code | §3.4 |
| Automatisations planifiées | **PARTIEL** | worker oui, ordonnanceur non | §3.5 |
| Mémoire sémantique | **PARTIEL** | stockage oui, vecteurs non | §3.6 |
| Citations traçables | **PARTIEL** | URL + extrait, pas de registre de preuve versionné | `web_research` |
| Observabilité / audit | **EXISTANT** | table d'audit + journal applicatif | `audit_logs` |
| Isolation des workers | **À CORRIGER** | worker dans le processus API | `main.py:137` |
| Gestion des quotas fournisseurs | **À CORRIGER** | seul le vocal est plafonné | `grep quota` |
| Allowlist web | **À CORRIGER** (décision en attente) | lecture limitée à 3 domaines en production | `BROWSER_OPEN_WEB=false` |

---

## 5. Analyse des sept skills du package

### 5.1 Constat commun

- **Format** : `SKILL.md` avec frontmatter `name` + `description` uniquement — **compatible** avec
  Hermes 0.21.7 (le slug est lu depuis `name:`, `gateway/run.py:2779`). Les skills natifs de ce
  dépôt ajoutent `version`, `author`, `license`, `metadata.hermes` — non requis, mais recommandés
  pour rester cohérent.
- **Nature** : consignes de méthode, aucun code, aucun schéma, aucune permission. Le README le dit
  lui-même : « un skill décrit une méthode ; il ne donne aucun droit ».
- **Conséquence** : copiés dans `~/.hermes/skills/`, ils changent la méthode de **l'agent Hermes**,
  pas les capacités du produit Kwes. Ils ne créent aucune route, aucun worker, aucune table.
- **Conflit de nom** : aucun des sept noms n'existe déjà (`kwes-development`, `kwes-product-ux`,
  `kwes-frontend-browser-check` sont installés, noms différents). Pas de collision.
- **Risque majeur** : ces skills décrivent des capacités que Kwes **n'a pas** (e-mail, agenda,
  fichiers). Installés tels quels, ils pousseraient l'agent à promettre des actions impossibles —
  exactement ce que la règle « ne jamais inventer un outil » interdit. Les installer sans les
  implémentations serait une régression de fiabilité.

### 5.2 Verdict par skill

| Skill | Compatibilité Hermes | Outils requis | Ce qui manque dans Kwes | Conflit | Recommandation |
|---|---|---|---|---|---|
| `kwes-research` | Oui (frontmatter minimal) | recherche, extraction, navigateur, citations | fournisseur à clé, PDF, registre de preuves, quotas | non | **Traduire en compétence Kwes** : étendre `web_research` (providers, preuve, dédup) |
| `kwes-files` | Oui | upload, MIME, AV, OCR, parsing, stockage objet, index | tout | non | **Spécification** : nouvelle compétence `files` + route d'import + storage |
| `kwes-email` | Oui | OAuth, lecture, brouillon, approbation hashée | tout | non | **Spécification** : connecteur + R2 avec approbation |
| `kwes-agenda` | Oui | calendrier, fuseaux, conflits, rappels | tout | non | **Spécification** : connecteur + objets événement |
| `kwes-automations` | Oui | ordonnanceur durable, triggers, DLQ | ordonnanceur, triggers, DLQ | non | **Spécification** : scheduler + table `workflows`/`runs` |
| `kwes-memory` | Oui | embeddings, retrieval hybride, ACL | embeddings, recherche vectorielle, expiration | non | **Traduire** : brancher pgvector + retrieval hybride |
| `kwes-orchestrator` | Oui | plan, policy, approbations, statuts | rien de bloquant | **recouvre** l'orchestrateur existant | **Ne pas installer** : duplique un composant fonctionnel (règle « ne pas réécrire ce qui marche ») |

### 5.3 Adaptations minimales si installation Hermes souhaitée

1. Ajouter `version`, `author`, `license`, `metadata.hermes.tags` au frontmatter.
2. Renommer les descriptions en « Use when… » (convention des skills natifs).
3. Retirer ou marquer explicitement comme **non disponible** les capacités absentes (email, agenda,
   fichiers) pour éviter toute promesse.
4. Installer **au plus** `kwes-research` et `kwes-orchestrator` (méthode), et seulement après
   validation — les cinq autres n'ont de sens qu'avec leur implémentation.

---

## 6. Problèmes et vulnérabilités identifiés

| # | Problème | Gravité | Impact | Correctif proposé |
|---|---|---|---|---|
| 1 | Worker dans le processus API | **Élevée** | une tâche longue (OCR, navigateur) bloque les requêtes | worker séparé (service), file Redis déjà là |
| 2 | Aucun ordonnanceur | **Élevée** | automatisations impossibles | scheduler durable + table `workflow_runs` |
| 3 | Aucun parseur PDF | Moyenne | documents PDF illisibles | `pypdf` + extraction page par page |
| 4 | pgvector inutilisé | Moyenne | mémoire sans recherche sémantique | embeddings + index HNSW + retrieval hybride |
| 5 | Allowlist web fermée | Moyenne (décision) | recherche limitée à 3 domaines | décision `BROWSER_OPEN_WEB` en attente |
| 6 | Aucun quota de recherche | Moyenne | coût imprévisible dès qu'un provider payant est ajouté | budget par provider + compteur |
| 7 | Pas de registre de preuves | Moyenne | citation = URL, pas de contenu horodaté conservé | table `evidence` (contenu, hash, date) |
| 8 | Mémoire sans expiration appliquée | Faible | faits périmés réinjectés | filtre `expires_at` au retrieval |
| 9 | Bouton « Joindre » inerte | Faible | attente produit déçue | retirer ou brancher avec l'import |
| 10 | Skills du package sans implémentation | **Élevée si installés tels quels** | promesses impossibles | ne pas installer avant implémentation |

**Aucune faille de type injection SQL, SSRF ou contournement d'authentification n'a été trouvée**
dans le code audité : la validation d'URL, la résolution DNS, le refus des IP privées, l'auth par
jeton et la RLS sont en place et testés.

---

## 7. Architecture cible

```
PWA → nginx/TLS → API (auth JWT, rate limit, tenant du jeton)
                     │
                     ├── Orchestrateur (DeepSeek) : intention → plan → policy → exécution
                     ├── Policy Engine (R0–R4, approbations hashées, audit) ← autorité unique
                     ├── Registre de compétences (manifeste + code + schémas + tests)
                     │     ├─ research   (providers + extraction + PDF + preuves)
                     │     ├─ files      (import → quarantaine → parse/OCR → index)
                     │     ├─ email      (lecture, brouillon, envoi approuvé)
                     │     ├─ agenda     (UTC + IANA, conflits, rappels)
                     │     ├─ memory     (pgvector, hybride, ACL, expiration)
                     │     └─ automations(scheduler durable, triggers, DLQ)
                     ├── Voix : Gemini Live (WebSocket serveur à serveur)
                     └── Audit append-only
Workers séparés : navigateur, OCR/indexation, planificateur
Données : PostgreSQL/Supabase (vérité) · Redis (files, verrous, non durable) · Storage (fichiers)
```

**Règles préservées** : DeepSeek reste le raisonnement ; Gemini reste la voix ; Supabase/PostgreSQL
la source de vérité ; Redis non durable ; API indépendante du gateway Hermes ; le Policy Engine
reste la seule autorité, y compris pour les sept compétences — un skill ne peut ni élargir ses
droits, ni appeler un autre skill sans repasser par la politique.

---

## 8. Plan d'implémentation priorisé

| Phase | Contenu | Dépendances | Complexité | Risques | Tests d'acceptation | Rollback |
|---|---|---|---|---|---|---|
| **P0** Décisions | cible des 7 skills, provider de recherche, embeddings, storage | — | S | bloquer le reste | décisions écrites | — |
| **P1** Recherche | provider à clé (Brave/SearXNG), extraction PDF, dédup, registre de preuves, quotas | P0 | **M** | coût, qualité, ToS | 20 requêtes réelles, sources citées, 0 invention, quota respecté | flag `research_provider=legacy` |
| **P2** Mémoire | embeddings, index HNSW, retrieval hybride, expiration, provenance | P0 | **M** | coût embeddings, fuite inter-utilisateurs | recherche sémantique > lexicale, ACL testée | désactiver le vecteur (retour tri par date) |
| **P3** Fichiers | route d'import, quarantaine, MIME, AV, PDF/DOCX/XLSX, OCR, storage | P1 (extraction), P0 (storage) | **L** | malwares, faux MIME, coût OCR | 8 formats, refus d'un fichier piégé, isolation | désactiver l'import (route masquée) |
| **P4** Agenda | connecteur calendrier, événements, fuseaux, conflits, rappels | P5 (scheduler) | **M** | OAuth, invitations externes | conflit détecté, fuseau exact, annulation approuvée | déconnecter le connecteur |
| **P5** Automatisations | scheduler durable, `workflows`/`runs`, triggers, DLQ, pause/reprise | — | **L** | double exécution, tâches fantômes | survie au redémarrage, idempotence, DLQ | arrêter le service scheduler |
| **P6** E-mail | OAuth scopes minimaux, lecture, brouillon, envoi approuvé | P5 (si envoi programmé) | **M** | envoi accidentel, fuite de tokens | brouillon ≠ envoi, payload modifié invalide l'approbation | révoquer le connecteur |

**Ordre recommandé** : P1 → P2 → P3 → P5 → P4 → P6. Chaque phase : migration versionnée, tests,
déploiement, puis validation explicite avant la suivante.

**Effort indicatif** : P1 ≈ 2 jours · P2 ≈ 2 jours · P3 ≈ 4-5 jours · P5 ≈ 3-4 jours · P4 ≈ 2-3 jours ·
P6 ≈ 2-3 jours (hors validation par des tiers).

---

## 9. Dépendances et coûts éventuels

| Élément | Dépendance | Coût | Statut |
|---|---|---|---|
| Fournisseur de recherche | Brave Search API, Tavily, Exa ou SearXNG auto-hébergé | payant (à vérifier) ou gratuit si auto-hébergé | **non installé, non souscrit** |
| Extraction PDF | `pypdf` (local) | gratuit | non installé |
| OCR | Tesseract (local) ou service cloud | gratuit (local) / payant (cloud) | non installé |
| Embeddings | Gemini embedding ou modèle local | payant à l'usage / gratuit en local | non installé |
| Stockage fichiers | Supabase Storage ou disque local | inclus / gratuit | non configuré |
| Calendrier / e-mail | Google Workspace ou autre | dépend du compte | non configuré |

Aucune souscription, aucun achat, aucune installation n'a été effectué pendant cet audit.

---

## 10. Décisions nécessitant ton approbation

1. **Cible des sept skills** : (a) les traduire en compétences Kwes réelles (recommandé),
   (b) les installer seulement pour l'agent Hermes, (c) les deux.
2. **Fournisseur de recherche** et budget mensuel plafond.
3. **Embeddings** : Gemini (payant à l'usage) ou modèle local (gratuit, moins bon).
4. **Stockage des fichiers** : Supabase Storage ou disque local.
5. **OCR** : Tesseract local (gratuit) ou service cloud.
6. **Ouverture web** `BROWSER_OPEN_WEB` (décision déjà en attente depuis la migration vocale).
7. **E-mail** : compte à connecter, scopes (lecture seule d'abord ?), politique d'envoi.
8. **Agenda** : Google Calendar ou calendrier local.
9. **Worker séparé** : créer un service `kwes-worker` (recommandé, prérequis de P3 et P5).

---

## 11. Preuves techniques

**Chemins examinés**
- `backend/app/agent/` (orchestrator, planner, policy, tools, gemini_live, voice, deepseek, audit)
- `backend/app/skills/` (registre + 5 compétences), `backend/app/api/` (11 routeurs)
- `backend/app/core/` (config, security, middleware, rate_limit), `backend/app/db/models.py`
- `supabase/migrations/0001…0010`, `frontend/src/lib/`, `frontend/src/screens/`
- `~/.hermes/skills/` (62 skills), `~/.hermes/hermes-agent/gateway/run.py:2779`
- Package extrait dans `~/.hermes/cache/scratch/kwes-audit/package/` (11 fichiers)

**Commandes exécutées**
```
hermes --version · python3 --version · importlib.metadata (12 paquets)
find ~/.hermes/skills -name SKILL.md · ls backend/app/skills
grep CHAT_TOOL_NAMES · grep scheduler|cron · python -c "import pypdf"
grep smtp|imap|oauth|calendar · grep embedding · grep quota
ss -ltnp · docker ps · psql: 17 tables, 39 politiques
pytest -q (148) · vitest run (134) · npm run build
```

**Tests et preuves de fonctionnement**
- 148 tests backend verts, 134 tests frontend verts, build Vite OK.
- Session vocale réelle Gemini Live (4,2 s de réponse via WSS public), table `voice_sessions` alimentée.
- Recherche web réelle : 2 sources lues et citées sur un cas ; 0 source annoncée honnêtement sur un autre.
- Lecture navigateur réelle : pages JavaScript rendues (Wikipédia 1,1 Mo de HTML, citations extraites).
- Document réel créé, téléchargé et ouvert depuis l'interface.
- Audit : chaque appel d'outil écrit dans `audit_logs` (vérifié en base).

**Limites de cet audit**
- Aucune lecture des secrets (clés non affichées, non copiées).
- Aucun test de charge, aucune revue de sécurité externe.
- Les coûts fournisseurs ne sont pas vérifiés (pas de compte souscrit) : ils sont à confirmer avant engagement.
- Le package n'a pas été exécuté : il ne contient pas de code exécutable.

---

*Rapport produit en lecture seule. Aucun fichier de production, aucune configuration, aucune base,
aucun service n'a été modifié. En attente de validation avant toute implémentation.*

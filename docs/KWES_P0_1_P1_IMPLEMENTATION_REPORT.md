# KWES — Rapport d'implémentation P0.1 + P1

**Mission** : sécurisation de l'authentification (P0.1) puis moteur de recherche web (P1)
**Date** : 16–17 novembre 2026 · **Commit de départ** : `cd7f0a6`
**Sauvegarde avant migrations** : `/home/babayaga/backups/kwes-pre-p0-20261116-2205.tgz`
**Statut** : P0.1 terminé et vérifié · P1 terminé et vérifié · P2 non commencé

---

## 1. Résumé exécutif

**P0.1** : l'API acceptait encore un jeton HS256 signé avec le secret de développement parce que
`decode_token` ne distinguait pas les environnements. `APP_ENV=production` est désormais explicite ;
en production, seul un ES256 Supabase est accepté, avec vérification de la signature via JWKS, de
l'expiration, de l'émetteur (`<supabase>/auth/v1`), de l'audience (`authenticated`) et du sujet.
Toute autre valeur d'algorithme est refusée avant même la vérification de signature.
**15 tests dédiés** couvrent les huit cas exigés ; ils passent tous.

**P1** : un moteur de recherche modulaire remplace la recherche DuckDuckGo/Wikipédia d'origine,
sans la supprimer (repli conservé). SearXNG auto-hébergé répond en local, sans clé ni abonnement.
Le moteur planifie, interroge, déduplique, classe, lit (HTML via Chromium, PDF via pypdf), enregistre
chaque lecture comme preuve en base et ne rédige que ce qu'il a réellement lu.
**72 tests** couvrent recherche, PDF, preuves, sécurité et non-régression du moteur.

**Incident à signaler** : la montée de version du skill `web_research` (1.0.0 → 1.1.0) a fait échouer
le démarrage de l'API pendant environ deux minutes (`uq_skill_versions_one_active`). Cause identifiée,
corrigée (l'ancienne version est rétrogradée en `deprecated`), couverte par un test de régression.
Le service est stable depuis.

---

## 2. Correction de l'authentification (P0.1)

### Cause exacte

`decode_token` choisissait la branche ES256 **si et seulement si** l'algorithme du jeton était ES256
et que `SUPABASE_URL` était défini ; sinon il tombait sur la branche HS256, **quel que soit**
`app_env`. Comme `APP_ENV` n'était pas défini, `app_env` valait `dev`, donc `jwt_secret` renvoyait
`DEV_JWT_SECRET` et n'importe quel porteur de ce secret pouvait forger un jeton accepté en production.

### Correctifs

| Élément | Avant | Après |
|---|---|---|
| Environnement | `APP_ENV` absent → `dev` | `APP_ENV=production` dans `backend/.env` |
| Alias | — | `production`/`prod` → `prod`, `development` → `dev` (validation stricte) |
| Production | HS256 accepté | **ES256 uniquement**, tout autre `alg` refusé avant vérification |
| Émetteur | non vérifié | `iss` = `https://<ref>.supabase.co/auth/v1` obligatoire |
| Audience | `authenticated` | `authenticated`, claim requis |
| Expiration | vérifiée | `require_exp` + `verify_exp` |
| Sujet | vérifié après coup | `require_sub` + UUID validé |
| Configuration incomplète | repli silencieux | refus explicite (`SUPABASE_URL` manquant = échec fermé) |
| `create_dev_token` | utilisable partout | lève `RuntimeError` si `is_production` |
| Journalisation | aucune | `auth.refus raison=…` (jamais le jeton) |

### Vérification en production

```
$ curl -o /dev/null -w '%{http_code}' .../api/v1/tasks -H "Authorization: Bearer <ES256 Supabase>"  → 200
$ curl -o /dev/null -w '%{http_code}' .../api/v1/tasks -H "Authorization: Bearer <HS256 dev>"        → 401
$ curl -o /dev/null -w '%{http_code}' .../api/v1/tasks                                               → 401
$ journalctl -u kwes-api | grep auth.refus
... auth.refus raison=algorithme_non_autorise alg=HS256
```

### Tests de sécurité (tous verts, `tests/test_auth_production.py`)

JWT ES256 valide → accepté · HS256 dev → refusé · expiré → refusé · signature invalide → refusé ·
émetteur invalide → refusé · audience invalide → refusé · `kid` inconnu → refusé · `alg: none` →
refusé · `SUPABASE_URL` absent → refusé · utilisateur non authentifié → 401 · utilisateur A lisant
la mission de B → 404.

RLS : **42 politiques** en base (39 + 3 pour `evidence`), vérifiées par requête.
Policy Engine : 25 tests verts (`test_policy.py`, `test_auth.py`), aucun code d'approbation modifié.

---

## 3. Architecture finale de recherche

```
web_research (skill, v1.1.0)
   └── ResearchService
         ├── Query Planner        (1 à 3 requêtes, variantes explicites, sans réécriture silencieuse)
         ├── Provider Router      (SearXNG → DuckDuckGo → Wikipédia, disjoncteur par appel)
         │     ├── SearXNG        (auto-hébergé, JSON, 0 FCFA)
         │     ├── DuckDuckGo     (Instant Answer, sans clé)
         │     └── Wikipédia      (API de recherche, fr/en)
         ├── Result Normalizer    (URL canonique, suivi publicitaire retiré, domaine)
         ├── Deduplication        (URL + titre, fusion des provenances)
         ├── Source Evaluator     (officielle / organisation / média / communauté / inconnue)
         ├── Web Extractor        (Chromium, contenu principal, injections neutralisées)
         ├── PDF Extractor        (pypdf, page par page, chiffré/illisible/image détectés)
         ├── Evidence Registry     (table `evidence`, RLS, empreinte du contenu)
         └── Research Synthesizer (extractive, citations [n] rattachées aux preuves)
```

Le pipeline est appelé par le registre natif (`web_research`), donc soumis au Policy Engine R0,
à l'audit et au worker isolé. Aucun skill documentaire n'a été ajouté au registre.

---

## 4. Installation et configuration SearXNG

| Élément | Valeur |
|---|---|
| Image | `searxng/searxng:latest` (402 Mo) |
| Conteneur | `kwes-searxng`, `restart=unless-stopped` |
| Exposition | `127.0.0.1:8888` uniquement (pas d'accès public) |
| Configuration | `/home/babayaga/docker/searxng/config/settings.yml` (persistante) |
| Cache | volume `/home/babayaga/docker/searxng/cache` |
| Limites | `--memory 512m`, `--pids-limit 256`, `--cap-drop ALL`, +CHOWN/SETGID/SETUID, `no-new-privileges` |
| Healthcheck | `GET /healthz` toutes les 30 s |
| Format | JSON activé (`search.formats: [html, json]`) |
| Limiter | désactivé (instance privée, non publique) |

Vérifications :

```
$ docker ps --filter name=kwes-searxng → Up (healthy)
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8888/healthz → 200
$ curl -s "http://127.0.0.1:8888/search?q=assistants+vocaux+Afrique&format=json" → 52 résultats
$ docker stats kwes-searxng → CPU 0,74 % · MEM 184,6 Mio / 512 Mio
```

Engines en erreur au démarrage (wikidata, openstreetmap, torch) : sans effet sur la recherche web
générale ; ce sont des moteurs spécialisés nécessitant une clé ou un `contact_url`.

---

## 5. Fournisseurs et fallback

- Ordre réel : **SearXNG** d'abord ; DuckDuckGo puis Wikipédia seulement si moins de 3 résultats.
- Un fournisseur en échec est écarté pour le reste de l'appel (`failures`) et journalisé.
- Un fournisseur qui renvoie 0 résultat produit un avertissement explicite, pas une invention.
- Vérifié en réel : `1er appel → ['searxng'] · 6 résultats` ; `2e appel → ['searxng (cache)']`.
- Vérifié en test : SearXNG en panne → bascule DuckDuckGo, avertissement conservé.

---

## 6. Extraction PDF

`pypdf 6.4.0` installé dans le venv backend. Comportements mesurés :

| Cas | Résultat |
|---|---|
| PDF texte (2 pages) | `ok`, texte préfixé `[page n]`, pages conservées |
| PDF de 5 pages, limite 2 | `ok`, mention « document tronqué : 2 pages sur 5 » |
| PDF chiffré | `chiffré` + message « mot de passe requis » |
| PDF image (page blanche) | `sans_texte` + « OCR non pris en charge en P1 » |
| Fichier illisible | `invalide` (aucune exception propagée) |
| > 8 Mo | `trop_volumineux` |
| **PDF réel arXiv (2,2 Mo, 15 pages)** | `lue`, extrait « [page 1] Provided proper attribution… », preuve enregistrée |

Deux correctifs nécessaires découverts en réel : plafond de taille distinct pour les PDF
(`fetch_pdf_max_bytes = 8 Mo`, sinon troncature → `PdfStreamError`) et bascule automatique quand
Chromium signale un téléchargement (PDF sans extension `.pdf`).

---

## 7. Registre de preuves

Table `evidence` (migration `0012`), 1 ligne = 1 lecture réussie :

`id`, `user_id`, `task_id`, `url`, `canonical_url`, `domain`, `title`, `excerpt`, `content`,
`content_hash` (SHA-256 du contenu normalisé), `provider`, `extraction_status`, `published_at`,
`fetched_at`, `provenance` (JSONB), `created_at/updated_at`.

Index : `(user_id, fetched_at desc)`, `(user_id, canonical_url)`, `domain`, `task_id`,
unique `(user_id, content_hash)`. RLS : select/insert/delete limités à `auth.uid()`.

Règles appliquées :
- une URL trouvée par un moteur **n'est jamais** une preuve ;
- une ligne n'est créée qu'après extraction réussie (`statut = lue`) ;
- même contenu pour le même utilisateur = même preuve (pas de doublon) ;
- consultation : `GET /api/v1/evidence` (privé, filtré par utilisateur).

Preuve réelle : mission `4e8bbb2f…` → 4 sources, **3 preuves**, fournisseur `searxng`.

---

## 8. Déduplication et classement

- Canonicalisation : schéma/hôte en minuscules, `www.` retiré, port par défaut retiré, fragment
  supprimé, paramètres de suivi retirés (`utm_*`, `gclid`, `fbclid`, `ref`, `source`…), tri des
  paramètres. Les paramètres inconnus sont **conservés** (deux pages réellement différentes ne
  doivent pas fusionner).
- Déduplication : par URL canonique **et** par titre normalisé sur le même domaine ; fusion des
  provenances et conservation de l'extrait le plus long.
- Classement : poids de catégorie (officielle 3,0 · organisation 2,0 · média 1,6 · inconnue 1,0 ·
  communauté 0,6) + accord entre fournisseurs (+0,4 par fournisseur) + position + recouvrement
  lexical avec la requête. La popularité n'entre pas dans le score.

---

## 9. Cache et quotas

| Élément | Valeur |
|---|---|
| Cache | Redis, clé = SHA-256(`provider|query|limit|langue`) |
| TTL | 86 400 s (24 h) — TTL réel observé : 86 305 s |
| Clés après 2 missions | 4 |
| Quota | compteur journalier par fournisseur (`kwes:research:quota:<provider>:<date>`) |
| Limite | 500 requêtes/jour/fournisseur (configurable) |
| Concurrence | 4 lectures simultanées (`research_concurrency`) |
| Anti-boucle | nombre de requêtes plafonné par la profondeur (1/2/3-4) |
| Panne Redis | cache et quota deviennent inopérants, la recherche continue (testé) |

Budget fournisseur : **0 FCFA**. Aucun fournisseur payant n'est instancié, aucune clé de recherche
n'est requise.

---

## 10. Protections SSRF et navigateur

Vérifié en réel avec le fetcher de production :

```
OK    https://example.com                          → 1 989 caractères
REFUS http://127.0.0.1:8888/                       → « Port non autorisé. »
REFUS http://169.254.169.254/latest/meta-data/     → « Hôte interne ou metadata refusé. »
REFUS http://localhost:8000/api/v1/health          → « Hôte interne ou metadata refusé. »
```

Tests automatisés supplémentaires : DNS rebinding (hôte public résolvant vers 10.1.2.3) refusé ;
redirection 302 vers `127.0.0.1` refusée avant suivi ; ports non web refusés ; schémas non HTTP
refusés. Injection de prompt : phrases hostiles neutralisées **à la phrase** (correctif nécessaire :
le texte extrait arrive sur une seule ligne, remplacer la ligne entière effaçait le contenu légitime),
avertissement remonté à l'utilisateur, contenu jamais interprété comme instruction.

SearXNG n'est joignable que depuis `127.0.0.1:8888` (`docker port` le confirme).

---

## 11. Fichiers créés et modifiés

**Créés — P0.1**
- `backend/tests/test_auth_production.py` (15 tests)
- `tools/sb_refresh.py` (outil de rafraîchissement du jeton de test, sans secret en clair)

**Créés — P1**
- `backend/app/research/core.py` — URL, déduplication, classement, sélection de passage
- `backend/app/research/providers.py` — SearXNG / DuckDuckGo / Wikipédia, cache, quotas, routeur
- `backend/app/research/planner.py` — plan de requêtes déterministe
- `backend/app/research/extract.py` — extraction PDF
- `backend/app/research/evidence.py` — registre de preuves
- `backend/app/research/service.py` — pipeline complet
- `backend/app/api/evidence.py` — `GET /api/v1/evidence`
- `supabase/migrations/0012_evidence.sql`
- `backend/tests/test_research_core.py`, `test_research_providers.py`, `test_research_pdf.py`,
  `test_research_evidence.py`, `test_research_security.py`, `test_skill_seed.py`

**Modifiés**
- `backend/app/core/security.py` — séparation stricte production / dev
- `backend/app/core/config.py` — alias d'environnement, `jwt_issuer`, réglages recherche, `fetch_pdf_max_bytes`
- `backend/app/skills/web_research/skill.py` — moteur v2 + repli legacy
- `backend/app/skills/web_research/schemas/output.json` — champs `evidence_ids`, `providers_used`, `queries`
- `backend/app/skills/web_research/manifest.yaml` — version 1.1.0
- `backend/app/skills/fetch.py` — `raw` pour les PDF, `sanitize_text`, neutralisation phrase par phrase
- `backend/app/skills/base.py` — `FetchedPage.raw`
- `backend/app/skills/render.py` — PDF sans rendu, téléchargement détecté
- `backend/app/skills/registry.py` — normalisation avant validation (P0)
- `backend/app/db/models.py` — modèle `Evidence`
- `backend/app/main.py` — routeur evidence, seed avec rétrogradation de version
- `backend/tests/conftest.py`, `test_infra.py` — worker inline en test, 18 modèles
- `backend/.env` — `APP_ENV=production`, `BROWSER_OPEN_WEB=true`

---

## 12. Migrations exécutées

| Migration | Contenu | Destructive ? |
|---|---|---|
| `0011_task_claims.sql` | `tasks.claimed_by/claimed_at` + index (P0) | non |
| `0012_evidence.sql` | table `evidence`, 4 index, 3 politiques RLS | non |

Sauvegarde du dépôt avant P0 : `/home/babayaga/backups/kwes-pre-p0-20261116-2205.tgz` (509 Ko).

---

## 13. Résultats des tests

| Suite | Référence | Résultat |
|---|---|---|
| Backend | 163 (P0) | **235 passed** (+72) |
| Frontend | 134 | **134 passed** |
| Build frontend | réussi | **réussi** (4,75 s) |
| Auth production | — | **15/15** |
| Policy Engine / auth | — | **25/25** |
| Recherche (cœur, fournisseurs, PDF, preuves, sécurité) | — | **57** |
| Seed de version | — | **1** (régression de l'incident) |

Détail P1 : cœur 13 · fournisseurs 10 · PDF 7 · preuves/pipeline 8 · sécurité 17 · (les compteurs
incluent les cas paramétrés).

Couverture explicite des exigences de la mission :

- **Recherche** : simple, multi-requêtes (2–3), fournisseur indisponible, fallback DDG, fallback
  Wikipédia, aucun résultat, déduplication, classement, cache 24 h, quotas, PDF texte, PDF malformé,
  PDF chiffré, PDF sans texte.
- **Sécurité** : SSRF, DNS rebinding, redirection vers IP privée, localhost, injection de prompt,
  isolation entre utilisateurs, RLS, absence de secrets dans les journaux.
- **Fiabilité** : Redis indisponible, SearXNG indisponible, redémarrage du worker, timeout,
  erreur d'extraction, reprise d'une mission.
- **Non-régression** : backend complet, frontend, build, authentification, Policy Engine, API,
  intégration worker.

---

## 14. État des services

| Composant | État | Preuve |
|---|---|---|
| `kwes-api.service` | active | `systemctl is-active` → `active` |
| `kwes-worker.service` | active | idem |
| Redis | healthy, AOF activé | `docker ps` |
| PostgreSQL | healthy, 18 tables, 42 politiques | `psql` |
| SearXNG | healthy | `/healthz` 200 |
| HTTPS public | 200 | `https://n8n.streetflexs.store/kwes-api/api/v1/health` |

Mission de contrôle après correctifs : `4e8bbb2f-cb88-4d1f-b46b-6cdf4db6359d` → **completed**,
4 sources, 3 preuves, fournisseur `searxng`.

---

## 15. Consommation de ressources

| Composant | CPU | Mémoire | Limite |
|---|---|---|---|
| `kwes-searxng` | 0,74 % | 184,6 Mio | 512 Mio |
| `kwes-redis` | 1,15 % | 5,9 Mio | 640 Mio |
| `kwes-postgres` | 0,01 % | 50,8 Mio | 1 Gio |
| Machine | charge 0,10 | 3,3 / 7,8 Gio utilisés | — |

Disque : 45 Go utilisés sur 96 Go (52 Go libres), dont ~400 Mo pour l'image SearXNG.

---

## 16. Coûts réels

| Poste | Coût |
|---|---|
| SearXNG | **0 FCFA** (auto-hébergé, image libre) |
| DuckDuckGo Instant Answer | 0 FCFA (sans clé) |
| Wikipédia API | 0 FCFA |
| `pypdf` | 0 FCFA (licence BSD) |
| Recherche totale | **0 FCFA/mois** |

Aucun abonnement, aucune clé de recherche, aucun fournisseur payant. Les seuls coûts variables du
produit restent ceux déjà connus : DeepSeek (raisonnement) et Gemini (voix), hors périmètre P1.

---

## 17. Risques et limitations

1. **Qualité des sources** : SearXNG agrège des moteurs publics ; le classement privilégie les
   sources officielles, mais une source officielle peut rester hors du top 5. La synthèse est
   extractive : elle ne comble aucune lacune.
2. **Pages illisibles** : certains sites renvoient 403/CAPTCHA ou du contenu vide. Le statut est
   alors `illisible` ou `vide` et l'utilisateur est averti — aucun contournement n'est tenté.
3. **PDF volumineux** : au-delà de 8 Mo, refus explicite. Pas d'OCR (P3).
4. **Pas de synthèse LLM** : volontairement, en P1, pour éviter toute hallucination et tout coût.
   Le raisonnement peut être ajouté en P2 avec ancrage obligatoire sur les preuves.
5. **SearXNG dépend de moteurs tiers** : une panne généralisée fait basculer sur DDG/Wikipédia, avec
   une couverture moindre.
6. **`APP_ENV=production`** : les tests et outils locaux doivent désormais utiliser `app_env=test`
   ou `dev` (les fixtures le font déjà).
7. **Incident P1** : la montée de version a brièvement coupé l'API ; le mécanisme de version est
   maintenant couvert par un test, mais toute nouvelle version de skill doit être vérifiée en
   préproduction avant redémarrage.

---

## 18. Commit Git

Commit unique de la mission : **`b6d2e9e`** — `feat(p1): moteur de recherche multi-fournisseurs,
preuves et authentification stricte`. Message complet :

```
feat(p1): moteur de recherche multi-fournisseurs + preuves + auth production
```

Contenu : sécurité JWT, package `app/research`, migration `0012`, routeur `/evidence`,
tests P0.1/P1, documentation. Aucun secret, aucun jeton, aucune sauvegarde `.env` dans le commit.

---

## 19. Procédure de rollback

**Recherche (P1)** — retour immédiat à l'ancien moteur, sans redéploiement :

```bash
# dans backend/.env
RESEARCH_ENGINE=legacy
sudo systemctl restart kwes-api kwes-worker
```

Le moteur v2 reste installé ; les preuves déjà enregistrées restent consultables.

**Authentification (P0.1)** — déconseillé, mais possible :

```bash
# revenir à l'ancien comportement (HS256 accepté) : NE PAS FAIRE EN PRODUCTION
APP_ENV=dev
sudo systemctl restart kwes-api kwes-worker
```

**SearXNG** :

```bash
sudo docker stop kwes-searxng          # la recherche bascule sur DDG/Wikipédia
sudo docker rm kwes-searxng            # suppression complète
```

**Migration `0012`** (destructive, uniquement si nécessaire) :

```sql
drop table if exists public.evidence;
```

**Code** :

```bash
git revert --no-edit <commit P1>
cd backend && .venv/bin/python -m pytest -q   # attendu : 163 passed
sudo systemctl restart kwes-api kwes-worker
```

---

## Annexe — preuves techniques

```
$ systemctl is-active kwes-api kwes-worker                → active / active
$ curl -s -o /dev/null -w '%{http_code}' .../health       → 200 (local et public)
$ docker ps --filter name=kwes-searxng                    → Up (healthy)
$ curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8888/healthz → 200
$ redis-cli --scan --pattern 'kwes:research:cache:*'      → 4 clés, TTL 86 305 s
$ redis-cli get kwes:research:quota:searxng:20261117      → 4
$ psql -c "select count(*) from pg_policies"              → 42
$ psql -c "select version,status from skill_versions where ..." → 1.0.0 deprecated · 1.1.0 active
$ pytest -q                                               → 235 passed in 57.44s
$ vitest run                                              → 134 passed
$ npm run build                                           → built in 4.75s
```

Mission réelle de bout en bout :

```
task 4e8bbb2f-cb88-4d1f-b46b-6cdf4db6359d → completed
sources 4 · preuves 3 · fournisseurs ['searxng']
  [lue]       esacode.org      (organisation) 3.64
  [lue]       capmad.com       (inconnue)     3.60
  [illisible] afrik.com        (inconnue)     3.12
  [lue]       elanteranga.com  (inconnue)     3.12
```

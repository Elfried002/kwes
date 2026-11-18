# Rapport final — finalisation SaaS de KWES

**Date :** 18 novembre 2026
**Branche :** `alpha/jour-1` (production)
**Commit initial de la mission :** `2c5032b` — **commit final :** `991cd75`
**Dépôt :** `Elfried002/kwes` (privé) · **Production :** https://www.agent-kwes.com

---

## 1. Audit des modifications Lovable

Deux branches distantes existaient : `feature/accueil-reponse-bornee` et
`feature/refonte-saas-audit-seo` (déjà fusionnée par PR #4 au moment de la reprise).

| Élément | Verdict |
|---|---|
| Réponse d'accueil bornée (6 lignes, défilable) | **Conservé** — correct, testé |
| Bandeau de mise à jour PWA + `pwa-update.ts` + `sw.js` v4 | **Conservé** — logique saine, 50 lignes de tests |
| `llms.txt` / `llms-full.txt` | **Conservé**, contenu vérifié (aucune capacité inventée) |
| Métadonnées SEO (canonical, OG, Twitter) | **Corrigé** — pointaient vers un domaine supprimé |
| JSON-LD | **Corrigé** — déclarait une `Organization` Kwes alors qu'aucune entité juridique n'existe ; remplacé par `SoftwareApplication` + `Brand` + `Person` |
| Aucun commit cassant détecté | — |

Rien n'a été réinitialisé. Les deux branches ont été fusionnées puis corrigées.

## 2. Architecture multi-tenant réellement mise en place

Migration `supabase/migrations/0013_tenants.sql` (appliquée en production) :

- `tenants`, `tenant_memberships` (rôles `owner`/`admin`/`member`/`viewer`), `tenant_settings` ;
- `tenant_id` ajouté sur **15 tables métier** (conversations, messages, tâches, étapes,
  exécutions, mémoires, approbations, intégrations, journal d'audit, notifications,
  documents, preuves, sessions vocales, connecteurs et commandes d'appareil) ;
- backfill complet depuis `user_id` et les tables parentes — **0 ligne orpheline** ;
- index de lecture par tenant ;
- un espace personnel par profil, identifiant = identifiant du profil (idempotent).

Côté application :

- résolution du tenant actif via `X-Tenant-Id`, **vérifiée contre l'appartenance réelle** ;
  un identifiant étranger renvoie 404, pas 403 (aucune fuite d'existence) ;
- toutes les lectures filtrées par `tenant_id` ; écritures estampillées par un hook
  `before_flush` alimenté par un `ContextVar`, donc même un chemin oublié (outil, worker)
  ne peut pas écrire une ligne orpheline ;
- le worker repose l'identité du demandeur avant d'exécuter une mission ;
- routes `/tenants` : liste, création, espace courant, membres, ajout et retrait.

## 3. Rôles, RLS et résultats

- Politiques réécrites sur **l'appartenance** (`is_tenant_member`, `can_write_tenant`,
  `can_manage_tenant` en `SECURITY DEFINER` pour éviter la récursion), plus aucune
  politique ne se contente de `user_id = auth.uid()` comme frontière.
- `ENABLE` + `FORCE ROW LEVEL SECURITY` sur **21 tables**.
- Rôle applicatif `kwes_app` : `NOSUPERUSER`, `NOBYPASSRLS`. L'application s'y connecte
  et déclare `request.jwt.claims` + `SET LOCAL role authenticated` à chaque transaction.
  Rollback immédiat : `KWES_RLS_ENABLED=false` + redémarrage.

**Preuves en production (base réelle) :**

```
user A -> conversations 14, tâches 6, tenants 1
user B -> conversations 48, tâches 44, tenants 1
sans claims -> conversations 0
écriture dans le tenant d'autrui -> InsufficientPrivilege (RLS)
```

**Tests d'isolation API** (`backend/tests/test_tenants.py`, 7 tests) :
liste vide chez l'autre utilisateur, 404 sur conversation/message/tâche/document/mémoire
par identifiant deviné, 404 si l'on réclame un tenant étranger, données séparées entre
espace personnel et espace d'équipe, `X-Tenant-Id` invalide rejeté.

## 4. Ce qui a été livré côté produit

| Domaine | État |
|---|---|
| Multi-tenant (base, API, RLS) | **Implémenté · testé · déployé** |
| Sélecteur d'espace (rail + tiroir) | **Implémenté · buildé** (vérifié en local, même bundle) |
| Titre KWES en grandes lettres sur l'accueil | **Implémenté · vérifié** (capture) |
| Suggestions sans débordement mobile | **Implémenté · déployé** |
| Bandeau de mise à jour PWA | **Implémenté** (repris de Lovable, tests inclus) |
| `robots.txt`, `sitemap.xml`, `llms.txt`, `llms-full.txt` | **Réécrits**, URL canonique unique |
| JSON-LD | **Valide** : `SoftwareApplication`, `Brand`, `Person` |
| API de production | **Confirmée** : `https://n8n.streetflexs.store/kwes-api/api/v1` |

## 5. URL publique de l'API — preuve

Ce n'est pas une supposition : `nginx` déclare `location /kwes-api/` →
`proxy_pass http://127.0.0.1:8000/api/v1/`, avec les blocs WebSocket dédiés
(`/kwes-api/api/v1/ws`, `/kwes-api/api/v1/voice/live`). Vérifications :

```
GET https://n8n.streetflexs.store/kwes-api/api/v1/health -> 200
GET .../conversations (jeton réel) -> 200, 48 lignes
CORS: access-control-allow-origin: https://www.agent-kwes.com
```

Le domaine `n8n.streetflexs.store` héberge aussi n8n, mais le préfixe `/kwes-api/` est
bien un reverse-proxy vers l'API Kwes. Une séparation sur un sous-domaine dédié reste
souhaitable ; elle exige un enregistrement DNS et un certificat, donc une décision.

## 6. Référencement

- Une seule URL canonique : `https://www.agent-kwes.com` (l'ancienne, `frontend-phi-pied…`,
  avait été supprimée et renvoyait 404).
- `robots.txt` : indexe le public, exclut `/api/` et `/kwes-api/`, déclare le sitemap.
- `sitemap.xml` : XML valide, une seule URL publique.
- Aucune route privée, aucun tableau de bord, aucune conversation dans le sitemap.
- Aucun fichier `llms*.txt` ne contient d'URL privée, de secret ou d'architecture sensible.

## 7. Build, tests, déploiement

```
backend  : 247 passed, 4 skipped
frontend : 138 passed, tsc propre
build    : vite OK
déploiement : push sur alpha/jour-1 -> production, statut Vercel « success »
```

## 8. Problèmes non résolus et risques résiduels

1. **Invitations par e-mail** : l'ajout d'un membre exige qu'un compte Kwes existe déjà.
   Aucun envoi d'e-mail n'est branché.
2. **Vérification visuelle en production** limitée : le pare-feu anti-bot de Vercel
   (`403 — Code 21`) bloque les navigateurs automatisés depuis ce serveur. La même
   build a été vérifiée en local contre l'API de production.
3. **Dépendances** : GitHub signale 64 vulnérabilités (1 critique, 20 élevées). Non
   traitées ici : elles touchent surtout la chaîne de build frontend.
4. **Séparation API/domaine** : l'API reste servie sous le domaine n8n.
5. **`kwes_app` et catalogue** : deux politiques dédiées autorisent l'écriture du
   catalogue de compétences (global, sans donnée client) ; tout le reste est filtré.
6. **Suppression de compte / export de données** : non implémentés.
7. **Sauvegarde** : `kwes-ops backup` exécuté avant migration
   (`/home/babayaga/backups/kwes-ops-20261118-0706.tgz`), copie de `.env` conservée
   hors dépôt avant activation de la RLS.

## 9. Rollback

| Objet | Procédure |
|---|---|
| RLS applicative | `KWES_RLS_ENABLED=false`, `kwes-ops restart-all` |
| Schéma | restauration de `kwes-ops-20261118-0706.tgz` |
| Frontend | redéploiement du commit précédent depuis Vercel |

Aucune donnée de production n'a été supprimée. `FORCE RLS` reste actif : c'est le
comportement voulu, et le rôle administrateur n'est plus utilisé par l'application.

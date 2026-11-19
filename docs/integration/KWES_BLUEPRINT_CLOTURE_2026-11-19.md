# KWES — Clôture du blueprint (complément)

**Date :** 19 novembre 2026 · **Périmètre :** staging (`kwes_staging`, `kwes-api-staging`). Production intacte.

## Ce qui a été ajouté depuis la livraison précédente

### Pont connecteurs → agents (le manque le plus important)
Un outil de connecteur n'existe pour l'agent que si le tenant possède une connexion **active**.
- `gmail.read` : lecture des derniers messages (Gmail API, jeton du coffre).
- `telegram.send` : envoi via le bot de l'utilisateur (Bot API).
- Sans connexion : `CONNECTOR_NOT_CONNECTED`, journalisé `error`, jamais simulé.
- Jetons lus au moment de l'appel, jamais injectés dans un prompt.

### Les spécialistes produisent désormais leur livrable
Un agent qui possède des outils et conclut sans en appeler un est **relancé une fois** explicitement.
Mesure avant/après sur la même mission : `kwes.business` passe de 0 à **1 preuve** et
`kwes.documents` produit un **document réel de 2 297 caractères** (vérifié : « 4/4 sources lues »).

### Quotas par espace
`tenant_quotas` (missions simultanées, missions/24 h, appels outils, tokens/mois) vérifiés
**avant** la création d'une mission, avec refus explicite. Défauts : 2 simultanées, 50/24 h.

### Suspension d'espace et kill-switch d'agent
- `POST /admin/tenants/{id}/suspend` — audité, bloque les nouvelles missions.
- `POST /admin/agents/{id}/toggle` — l'agent désactivé sort du catalogue du plan.
Les deux exigent `super_admin`/`ops_admin` ; `support_readonly` reçoit 403 (testé).

### Reprise automatique
Balayage toutes les 120 s : les missions `queued`/`running` sans activité depuis 10 min sont
relancées (2 maximum par cycle), via une connexion système, l'exécution restant sous RLS.

### Sentry
Initialisation si `SENTRY_DSN` est fourni ; sinon le cockpit affiche explicitement
« Aucun DSN configuré : aucune erreur n'est transmise ». Aucune valeur inventée.

## Défauts révélés par le staging (et corrigés)

| Défaut | Symptôme | Correction |
|---|---|---|
| `platform_roles` sans GRANT | 500 sur le cockpit admin | `grant select` à `authenticated` |
| `tenant_quotas` sans GRANT ni politique | 500 à la création de mission | `grant select, insert, update` + politique `tenant_quotas_member_write` |

Ces deux erreurs illustrent la règle : sous RLS, un `GRANT` et une **politique pour `authenticated`**
sont tous deux nécessaires — `kwes_app` bascule de rôle à chaque requête.

## Migrations

`0017`, `0018`, `0019` — appliquées **en staging uniquement**, avec `ON_ERROR_STOP`.

## Limites qui subsistent, dites franchement

1. **Aucun connecteur réel n'a été exercé** (pas d'identifiants Google/Telegram) : le pont est
   testé avec des réponses fournisseur simulées, pas avec un vrai compte.
2. **`kwes.documents` ne remonte pas de preuve structurée** alors qu'il crée bien un document
   (le livrable existe, le compteur de preuves reste à 0).
3. **Quotas** : les tokens/mois sont stockés mais pas encore bloquants (seuls la concurrence et
   le volume quotidien le sont).
4. **Sentry** non testé (pas de DSN) ; le chemin d'initialisation est couvert par le statut explicite.
5. **Pas de test de charge ni de restauration** ; l'isolation croisée sur les nouvelles tables
   reste à automatiser.

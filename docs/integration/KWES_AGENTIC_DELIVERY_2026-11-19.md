# KWES — Livraison du socle agentique (staging)

**Date :** 19 novembre 2026
**Périmètre :** staging uniquement (`kwes_staging`, `kwes-api-staging`). **Production inchangée** : aucune migration, aucun déploiement, aucun redémarrage de service de production.

---

## 1. Ce qui fonctionne réellement (preuves)

### Mission multi-agent de bout en bout
Mission `485d8e1f…` puis mission finale : **3 spécialistes** (`kwes.research`, `kwes.business`, `kwes.documents`), dépendances respectées (0 → 1 → 2), **10 événements** de journal, mission `completed` en ~65 s.

Journal réel (extrait) :
```
mission.started   running   objective=…
mission.planned   planned   tasks=[{seq:0, agent:kwes.research}, …]
task.started      running   tools=[research.synthesis, source.citation, web.page.read, web.search]
tool.invoked      ok        web_research  « prix cacao Côte d'Ivoire novembre 2026 »
task.finished     completed evidence=4 verified=true
mission.completed completed agents=[kwes.research, kwes.business, kwes.documents]
```

### Runtime des spécialistes
- outils traduits vers les skills réels (`web.search` → `web_research`, `web.page.read` → `browser_readonly`, `document.create` → `document_write`, `code.write.workspace` → `code_exec`) ;
- plafonds appliqués : 180 s, 12 appels, 4 tours LLM ; dépassement ⇒ arrêt contrôlé avec résultats partiels ;
- un outil non autorisé est refusé **sans être exécuté** et journalisé `denied` ;
- un résultat `completed` sans preuve n'est **jamais** vérifié (statut `partial`).

### Dispatcher Core
- plan demandé au modèle, validé contre le registre (agent inconnu ⇒ refus, outils non exécutables écartés) ;
- plan illisible ou vide ⇒ **décomposition déterministe** recherche → analyse → livrable (aucune donnée inventée) ;
- exécution par vagues, 4 tâches en parallèle au maximum, dépendances respectées, branche bloquée si une dépendance échoue ;
- plan persisté de façon idempotente (clé `mission:rang:agent`).

### Journal et reprise
- `run_events`, `tool_invocations` : arguments expurgés (`token`, `secret`, `password`, `api_key`… remplacés par `[REDACTED]`), sorties bornées ;
- `POST /missions/{id}/resume` rejoue uniquement les tâches non terminées ;
- le journal n'échoue jamais bruyamment : une erreur d'écriture est journalisée sans casser la mission (testé : c'est ainsi qu'a été détecté le défaut de séquence, corrigé).

### Connecteurs
- catalogue de 4 fournisseurs (Google, Microsoft, Telegram, WhatsApp) issu de manifestes YAML versionnés ;
- **statut honnête** : Google/Microsoft = `needs_configuration` tant que les identifiants serveur sont absents ; connexion refusée avec explication (pas de bouton mort) ;
- OAuth2 + PKCE, `state` à usage unique lié au tenant et à l'utilisateur (rejeu refusé) ;
- secrets chiffrés AES-GCM dans `connector_secrets`, référence non secrète, déchiffrement réservé au serveur ;
- déconnexion = suppression du secret ;
- test de connexion = vérification du secret présent et déchiffrable (aucun appel externe simulé).

### Cockpit d'administration
- `platform_roles` (5 rôles), vérification serveur sur chaque endpoint ;
- vue d'ensemble (espaces, membres, missions 30 j, en cours, échecs, alertes, appels/tokens LLM) ;
- liste des espaces et des missions (métadonnées seulement), usage par modèle ;
- annulation de mission réservée à `super_admin`/`ops_admin`, **auditée** dans `audit_logs` avec motif ;
- coût monétaire toujours `null` : aucun barème inventé.

### Frontend
- écran **Connecteurs** (statut, permissions expliquées, connexion, test, déconnexion, jeton manuel) ;
- écran **WhatsApp** (distinction personnel / Business App / Business Platform, prérequis Meta, statut réel « préparé mais non activé ») ;
- écran **Cockpit** (403 explicite hors administration).

---

## 2. Défauts réels trouvés en staging et corrigés

| Défaut | Symptôme | Correction |
|---|---|---|
| Séquence non accordée | `permission denied for sequence run_events_id_seq` | `grant usage, select on all sequences to authenticated` dans 0017 |
| Outils agents ≠ skills | agent sans outil, 0 preuve | table de correspondance `TOOL_SKILL_MAP` |
| Plan tronqué | `Sortie JSON invalide` (max_tokens 1200) | 2500 jetons + 4 tâches max + repli déterministe |
| Plan non conforme | clés variables selon le modèle | extraction tolérante (`tasks`/`plan`/`steps`/dict indexé) |
| Lecture RLS puis écriture admin | `database is locked` (SQLite) | transaction de rôle refermée avant l'opération |
| `Path` local dans `lifespan` | `UnboundLocalError` | import unique en tête de module |

---

## 3. Limites mesurées, non maquillées

1. **Les spécialistes aval n'utilisent pas encore leurs outils** : `kwes.business` et `kwes.documents` concluent sans appeler `business_planning` / `document_write` (preuves = 0). Le dernier livrable est donc honnête mais pauvre.
2. **Qualité des sources variable** : une mission a trouvé « 1 200 FCFA/kg » avec 4 sources, une autre a conclu « prix non disponible ». Le comportement est honnête ; la pertinence dépend de SearXNG et du modèle.
3. **Planification par le modèle instable** : le JSON du modèle est souvent inexploitable ; le plan déterministe prend le relais. C'est fiable, mais moins fin qu'un vrai raisonnement de plan.
4. **Pas de reprise automatique au redémarrage** : la reprise est explicite (`/resume`). Le balayage des missions orphelines reste à brancher.
5. **Connecteurs OAuth non testés en réel** : sans identifiants Google/Microsoft, seul le parcours (state, PKCE, refus) est prouvé ; l'échange de code réel n'a pas été exercé.
6. **WhatsApp non activé** : aucun compte WABA, aucun envoi réel. Les outils restent `declared`.
7. **Pas de Sentry** intégré ; pas d'alertes automatiques alimentées (table prête).
8. **Isolation multi-tenant** : prouvée au niveau SQL et applicatif les jours précédents (A voit 73 tâches, 0 de B) ; les nouvelles tables ont les mêmes politiques, mais un test croisé automatisé sur `agent_tasks`/`run_events` reste à ajouter.

---

## 4. Migrations

- `0017_agentic_socle.sql` — `agent_tasks`, `run_events`, `tool_invocations`, `connector_catalog`, `tenant_connections`, `oauth_states`, `cost_rates`, `platform_roles`, `admin_alerts` (+ RLS forcée, + GRANT séquences).
- `0018_connector_vault.sql` — `connector_secrets` (chiffré, RLS).

Appliquées **en staging uniquement**, avec `ON_ERROR_STOP`.

---

## 5. Secrets nécessaires (registre consolidé)

| Fournisseur | Secret / ID | Où l'obtenir | Scopes | Env | Priorité |
|---|---|---|---|---|---|
| Google | `GOOGLE_OAUTH_CLIENT_ID` | console.cloud.google.com → APIs & Services → Credentials | `gmail.readonly`, `gmail.compose`, `calendar.events` | staging puis prod | haute |
| Google | `GOOGLE_OAUTH_CLIENT_SECRET` | idem | — | staging puis prod | haute |
| Google | Écran de consentement + domaines vérifiés | console.cloud.google.com → OAuth consent screen | — | prod | haute (validation Google pour `gmail.send`) |
| Microsoft | `MICROSOFT_OAUTH_CLIENT_ID` | entra.microsoft.com → App registrations | `Mail.Read`, `Calendars.ReadWrite` | staging | moyenne |
| Microsoft | `MICROSOFT_OAUTH_CLIENT_SECRET` | idem (Certificates & secrets) | — | staging | moyenne |
| Meta / WhatsApp | App ID, App Secret, WABA ID, Phone Number ID | developers.facebook.com → app Business → WhatsApp | `whatsapp_business_messaging`, `whatsapp_business_management` | staging | moyenne (revue Meta 1–2 semaines) |
| Meta / WhatsApp | Jeton utilisateur système permanent | Business Settings → Utilisateurs système | idem | staging | moyenne |
| Telegram | Jeton de bot (par utilisateur) | @BotFather | bot | — | l'utilisateur le fournit lui-même |
| Sentry | DSN backend + frontend | sentry.io → projet | — | staging | basse |
| Sentry | Auth token lecture | sentry.io → Settings → Auth Tokens | `event:read` | staging | basse |

**Aucune valeur secrète n'est écrite dans ce document, le dépôt ou les logs.**

---

## 6. Ce qui attend une décision

1. Appliquer `0017`/`0018` en **production** (aucune donnée existante modifiée, mais c'est la production).
2. Fournir les identifiants Google : sans eux, la connexion Gmail/Agenda reste `needs_configuration`.
3. Valider le barème de coût (sinon le coût reste inconnu).
4. Décider du branchement d'un **worker de missions** (aujourd'hui le dispatcher tourne dans le processus API du staging ; un redémarrage interrompt la mission en cours, la reprise est manuelle).

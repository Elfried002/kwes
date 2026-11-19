# KWES — Rapport d'intégration agentique (staging)

**Date :** 19 novembre 2026
**Périmètre :** environnement de staging sur le VPS de production, base `kwes_staging`, services `kwes-api-staging` et `kwes-worker-staging`. **La production n'a pas été modifiée.**
**Décision de référence :** validation du 19/11 — travaux en staging autorisés, production soumise à validation distincte.

---

## 1. Environnement de staging créé

| Élément | État |
|---|---|
| Base `kwes_staging` | copie de la production (21 tables, 11 mémoires, 17 profils) |
| Rôle applicatif `kwes_app` + `authenticated` | droits appliqués sur toutes les tables |
| API staging | `127.0.0.1:8001`, service `kwes-api-staging`, santé **200** (`db ok`, `redis ok`, `llm ok`) |
| Worker staging | `kwes-worker-staging`, **RLS active, sans `DB_RLS_BYPASS`** |
| Redis | base logique `1` (isolée de la production, base `0`) |
| Package d'agents | `/opt/kwes-staging/agents_pkg` (V3.1, 77 fichiers) |
| Sauvegarde avant migration | `/var/backups/kwes/staging/pre-0016.dump` (1,2 Mo) |

---

## 2. Migration `0016` — appliquée en staging uniquement

**Cinq tables créées** : `agents`, `agent_capabilities`, `agent_runs`, `agent_messages`, `llm_usage`.

**Politiques RLS**
| Table | Politique | Portée |
|---|---|---|
| `agents` | `agents_read` (lecture) + `agents_write` (`to kwes_app`) | catalogue global |
| `agent_capabilities` | `agent_capabilities_read` + `agent_capabilities_write` | catalogue global |
| `agent_runs` | `agent_runs_tenant` | `is_tenant_member(tenant_id)` |
| `agent_messages` | `agent_messages_tenant` | `is_tenant_member(tenant_id)` |
| `llm_usage` | `llm_usage_tenant` | `is_tenant_member(tenant_id)` |

`FORCE ROW LEVEL SECURITY` sur les cinq tables.

**Contraintes vérifiées**
```
agent_capabilities_no_downgrade   empêche A3→R1 et A4→R2 (erreur de table)
agent_capabilities_approval_level_check  A0..A4
agent_capabilities_approval_mode_check   none|policy_checked|explicit|strong
agents_agent_id_format            agent_id like 'kwes.%'
clés étrangères                   agent_capabilities→agents (CASCADE),
                                  agent_runs→tenants/tasks/agent_runs,
                                  agent_messages→tenants/tasks,
                                  llm_usage→tenants
```

**Défaut trouvé et corrigé pendant l'application** : sans `GRANT` explicites, les nouvelles tables étaient inutilisables par l'API (`permission denied for table agent_runs`), car le rôle applicatif bascule en `authenticated` pendant une requête. Les `GRANT` sont désormais dans la migration.

---

## 3. Tests d'isolation — résultats

### 3.1 Au niveau SQL, avec le rôle applicatif réel (`kwes_app`)

```
lecture propre (A)           1      (écriture dans son tenant : acceptée)
lecture croisée (B depuis A) 0
insertion dans le tenant B   ERROR: new row violates row-level security policy
messages propres (A)         1
insertion message tenant B   ERROR: new row violates row-level security policy
```

### 3.2 Au niveau applicatif, avec le worker (RLS active)

```
tâches visibles par A : 73    | tâches de B visibles par A : 0
tâches visibles par B : 1
```

### 3.3 Exécution complète d'une mission sous RLS

Mission créée en staging avec une étape `code_exec` :

```
création     201
statut       completed
étape        code_exec completed
stdout       STAGING_RLS_OK
```

Le worker a donc réclamé la tâche, exécuté l'étape et écrit le résultat **sans contournement de la RLS**.

---

## 4. `DB_RLS_BYPASS` — ce qui a changé

| Avant | Après (staging) |
|---|---|
| Un seul `Database`, rôle propriétaire | `db` (rôle `kwes_app`, RLS) **+** `db_system` (propriétaire, gestion de file uniquement) |
| Claim et sweep dans le rôle propriétaire | inchangé, mais isolé dans `db_system` |
| Exécution des missions dans le rôle propriétaire | **exécution dans `db`**, avec claims posés par tâche |

Deux défauts corrigés au passage, tous deux révélés par le staging :

1. **L'amorçage lisait la tâche avant de connaître son demandeur** → « Tâche introuvable au démarrage ». Corrigé par une lecture d'identité via `db_system`, puis application du contexte avant toute lecture métier.
2. **L'identité était effacée à chaque fermeture de session** (`set_rls_user(None)` dans le teardown) → une mission multi-sessions perdait ses droits en cours d'exécution. Corrigé : la connexion est neutralisée, mais l'identité de la tâche reste portée par le contexte d'exécution.

**Rollback** : redémarrer `kwes-worker-staging` avec `DB_RLS_BYPASS=true` dans son unité ; aucune donnée à restaurer, la migration est indépendante du worker.

---

## 5. Instrumentation des tokens — opérationnelle

Une ligne par appel LLM, mesurée en staging sur un vrai appel :

```
modèle     gemini-3.8-live
fournisseur google
usage      chat
entrée     963 tokens
sortie     71 tokens
durée      14 744 ms
source     provider
tenant     attribué (non nul)
```

Champs disponibles par ligne : modèle, fournisseur, objectif (`purpose`), tokens entrée/sortie, durée, source (`provider`/`unavailable`), `cost_eur` (nullable), tenant, mission, agent.
L'agrégation par agent et par mission se fait par requête sur `agent_runs` + `llm_usage`.

**Aucun barème n'est fixé** : `cost_eur` reste nul tant que les tarifs ne sont pas validés.

---

## 6. Agent Research — état exact

Simulation exécutée en staging (`tools/simulate_research_agent.py`) :

```
registre          17 agents (1 orchestrateur, 16 spécialistes)
type              specialist | v1.1.0 | defined_not_activated
autonomie         A0, A1, A2 (A3/A4 soumis à Core + utilisateur)
timeout           180 s | 2 tentatives | 12 appels d'outils
isolation         kwes_app, contexte par tâche, bypass interdit
outils exécutables  web.search, web.page.read, research.synthesis, source.citation
outils déclarés      aucun
matrice           4 outils, tous A0/A1 sans approbation
fuite d'outil       aucune
contrat de tâche    valide (objectif, livrable, critères, langue fr)
résultat sans preuve  non vérifié  |  avec preuve  vérifié
verdict           prêt pour un pilote en staging
```

**Ce qui n'est pas fait** : aucun appel réel de l'agent Research via le répartiteur, parce que le répartiteur n'existe pas encore. La simulation valide le chargement, les permissions et le contrat, pas l'exécution déléguée.

---

## 7. Ce qui reste à valider par toi

| Élément | Pourquoi |
|---|---|
| Application de `0016` en production | cinq tables, aucune donnée existante modifiée, mais c'est la production |
| Bascule du worker de production sans `DB_RLS_BYPASS` | changement de comportement d'exécution ; rollback en 30 s |
| Barème de coût (€/million de tokens) | aucune valeur ne sera inventée |
| Mode de dépassement | refus par tâche, alerte par mission (recommandation) |
| Activation du pilote Research en production | après le répartiteur |

---

## 8. Risques résiduels

1. **Le répartiteur n'existe pas** : les 16 agents sont chargeables et validés, mais aucune mission multi-agents ne peut encore être distribuée.
2. **13 spécialistes sans outil exécutable** : leur doctrine est écrite, mais aucun outil réel ne peut encore être exécuté pour eux.
3. **Le worker de staging tourne sur la même machine que la production** : l'isolation est logique (base et Redis séparés), pas physique.
4. **La clé Gemini est partagée** entre staging et production : les essais de staging consomment le même budget. Les tests ont été limités à quelques appels.
5. **`cost_eur` reste nul** : pas de plafond financier actif, seulement des plafonds en unités (temps, appels).

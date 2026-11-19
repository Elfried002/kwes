# KWES — Intégration de l'équipe agentique : feuille de route

**Date :** 19 novembre 2026
**Objectif :** rendre KWES capable de charger, valider et orchestrer réellement ses 16 spécialistes dans un environnement SaaS multi-tenant, sans dégrader l'existant.
**État :** préparation terminée, **rien n'est déployé**. La production tourne toujours sur le moteur mono-agent.

---

## 1. Matrice de statut

### 1.1 Déjà fonctionnel en production (vérifié)

| Composant | Preuve |
|---|---|
| API FastAPI + auth Supabase | `https://api.agent-kwes.com/api/v1/health` → 200 |
| Missions mono-agent (plan, étapes, exécution, reprise) | 78 missions terminées, 8,8 s en moyenne |
| Worker + file Redis | claim TTL 120 s, aucune tâche perdue depuis la migration |
| Approbations humaines | `awaiting_approval` → approbation → `completed` (mission `304aef2b`) |
| RLS multi-tenant | `kwes_app` voit 54 conversations, 0 de l'autre tenant, insert croisé refusé |
| Skills | `web_research`, `browser_readonly` (rendu JS), `code_exec`, `document_write`, `remember`, `business_planning` |
| Voix Gemini Live | une voix, barge-in, narration d'outil (annonce à +1,0 s pendant un outil de 5 s) |
| Recherche + rendu JS | SearXNG 0,6–0,9 s, Chromium `quotes.toscrape.com/js/` → 10 blocs |
| Audit et preuves | `audit_logs`, `evidence`, 8/8 contrôles de bout en bout |

### 1.2 Développé dans cette étape (code écrit, testé, **non déployé**)

| Composant | Fichier | État |
|---|---|---|
| Schéma de validation d'agent | `backend/app/agents/schema.py` | écrit, 12 tests passent |
| Registre et chargeur (fail closed) | `backend/app/agents/registry.py` | écrit, testé sur le package réel : 17 agents, 0 erreur |
| Contrats inter-agents (tâche, résultat) | `backend/app/agents/contracts.py` | écrit, testé (résultat sans preuve = non vérifié) |
| Migration registre + exécutions | `supabase/migrations/0016_agents.sql` | **préparée, non appliquée** |
| Test d'isolation croisée | `tools/test_isolation_agents.sql` | préparé, à lancer après migration |
| Package V3.1 | `docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1/` | identités préservées, procédures réécrites, langue et budgets ajoutés |

### 1.3 À développer (pas encore écrit)

| Composant | Pourquoi ce n'est pas fait | Effort |
|---|---|---|
| Répartiteur de tâches (Core → spécialistes) | dépend du registre et des contrats, qui viennent d'être posés | 3–4 jours |
| Journal d'exécution alimenté (`agent_runs`) | nécessite la migration appliquée | 1 jour |
| Instrumentation des tokens | nécessaire avant tout plafond en euros | 1 jour |
| Retrait de `DB_RLS_BYPASS` pour l'exécution des agents | touche le worker en production : à faire sous validation, avec test croisé | 2 jours |
| Interface « Missions » multi-agents | affichage des agents, de leurs étapes et de leurs preuves | 3 jours |
| Tests bout en bout multi-agents | dépendent du répartiteur | 2 jours |

### 1.4 Nécessite ta validation (bloquant)

| Décision | Ce que je demande |
|---|---|
| Limites de budget (unités) | 180 s/tâche, 12 appels, 4 tours, 900 s/mission, 8 étapes, 4 agents en parallèle — voir `KWES_BUDGET_PROPOSAL.md` |
| Barème de coût (€/million de tokens) | aucune valeur ne sera fixée sans ton barème |
| Mode de dépassement | refus net par tâche, alerte par mission (recommandation) |
| Application de la migration `0016` | elle crée 4 tables, aucune donnée existante n'est touchée |
| Retrait de `DB_RLS_BYPASS` | changement de comportement du worker, avec rollback immédiat possible |
| Activation du premier agent pilote | `research`, après tests |

---

## 2. Décisions du 19/11/2026 — état d'application

| Décision | Application | Preuve |
|---|---|---|
| Procédures réellement distinctes pour les 16 | en cours (rédaction déléguée, vérification par mesure de similarité) | rapport de similarité à venir |
| Politique linguistique commune | **appliquée** aux 17 `SOUL.md` (Core + 16) | section « ## Langue » présente 17/17 |
| Budgets par tâche, agent, mission | **structure écrite** ; valeurs en unités proposées, euros en attente | `KWES_BUDGET_PROPOSAL.md` |
| Isolation : rôle applicatif + contexte par tâche, RLS active dans le worker | **déclarée** dans les 17 configs (`bypass_rls_forbidden: true`) ; le retrait effectif de `DB_RLS_BYPASS` reste à faire sous validation | `execution.isolation` dans les configs |
| Core ne modifie pas les permissions | **corrigée** : `may_change_user_permissions: false`, avec `can_request_permission_change_through_user_approval: true` | `core/config.yaml` + test de refus |
| Table A0–A4 ↔ R1–R4 | **écrite** | `shared/config/policy-mapping.yaml` |
| Registre, chargeur, schémas, contrats | **écrits et testés** | `backend/app/agents/`, `tests/test_agent_registry.py` (12 tests) |
| Répartiteur, journal, interface | **planifiés** (§1.3) | cette feuille de route |
| Ne rien modifier en production sans validation | respecté : aucune migration appliquée, aucun service redémarré | — |

---

## 3. La table de correspondance A0–A4 ↔ R1–R4

Publiée dans le package : `shared/config/policy-mapping.yaml`.

| Package | Moteur | Approbation | Exemple |
|---|---|---|---|
| A0 consultation | R0–R1 | aucune | lire une page, chercher |
| A1 préparation | R1 | aucune | brouillon, plan, document interne |
| A2 action réversible | R1–R2 | contrôle de politique | exécuter du code dans l'espace de travail |
| A3 action externe | **R2** | **explicite** | envoyer un email, publier, exécuter un workflow |
| A4 financier/critique | **R3–R4** | **forte** | paiement, suppression définitive |

Trois descentes sont **interdites et testées** : A3→R1, A4→R2, A2→R0. La contrainte SQL `agent_capabilities_no_downgrade` empêche qu'une erreur de table abaisse un niveau, et le chargeur refuse une matrice incohérente.

---

## 4. Isolation : comment on retire `DB_RLS_BYPASS`

Aujourd'hui :

- l'API se connecte en `kwes_app` et pose le contexte (`set role authenticated` + claims) **à chaque emprunt de connexion** ;
- le worker se connecte avec le rôle propriétaire (`DB_RLS_BYPASS=true`) parce qu'il traite les missions de tous les utilisateurs.

Cible : l'exécution d'un agent ouvre une session **par tâche**, avec le rôle `kwes_app` et le contexte du tenant de la mission. Le worker garde le rôle propriétaire **uniquement** pour réclamer les tâches dans la file (opération système sans donnée utilisateur).

Étapes :

1. Ajouter un contexte de tâche (`tenant_id`, `user_id`) dans `app/worker/runtime.py` et l'appliquer avant toute lecture de données métier.
2. Refuser au chargement tout agent dont `execution.isolation.bypass_rls_forbidden` est faux (déjà testé).
3. Exécuter `tools/test_isolation_agents.sql` : écrire dans son tenant → OK, lire l'autre → 0, écrire chez l'autre → refus.
4. Test de non-régression : les 8 contrôles du socle doivent rester verts après le changement.
5. Rollback : remettre `DB_RLS_BYPASS=true` dans l'unité `kwes-worker` et redémarrer (30 s).

---

## 5. Phases

### Phase 0 — Socle de chargement (2 jours) — *code prêt, reste la revue*
- [x] schéma, registre, contrats, tests (12)
- [ ] revue de code et fusion
- **Critère de sortie :** `AgentRegistry(package).load()` charge 17 agents, 0 erreur, et refuse 6 packages volontairement invalides.

### Phase 1 — Base de données (1 jour) — *attend validation*
- [ ] appliquer `0016_agents.sql` (4 tables, RLS, contrainte anti-descente)
- [ ] exécuter `tools/test_isolation_agents.sql` avec `kwes_app`
- **Critère de sortie :** écriture croisée refusée, lecture croisée à 0.

### Phase 2 — Répartiteur (4 jours)
- [ ] `POST /missions` avec plan multi-agents : Core produit des `AgentTask`
- [ ] exécution séquentielle puis parallèle (4 max), dépendances respectées
- [ ] `agent_runs` alimenté, `agent_messages` pour les contrats
- **Critère de sortie :** une mission à 2 agents produit 2 lignes `agent_runs` et 1 résultat agrégé avec preuves.

### Phase 3 — Isolation (2 jours) — *attend validation*
- [ ] contexte tenant par tâche, retrait de `DB_RLS_BYPASS` pour les agents
- [ ] test croisé rejoué, non-régression des 8 contrôles
- **Critère de sortie :** un agent ne peut lire aucune donnée d'un autre tenant, même avec un bug de filtre.

### Phase 4 — Budgets et observabilité (2 jours) — *attend ton barème*
- [ ] tokens et coût journalisés par exécution
- [ ] application des limites du §3
- **Critère de sortie :** une tâche qui dépasse 12 appels est arrêtée avec un code explicite, sans perte de preuve.

### Phase 5 — Agent pilote (2 jours) — *attend validation*
- [ ] activer `kwes.research` seul, en production, avec un quota réduit
- [ ] 10 missions réelles, résultat comparé au mono-agent
- **Critère de sortie :** 10/10 missions terminées avec preuves, aucune régression de latence au-delà de 20 %.

---

## 6. Migrations

| Fichier | Contenu | État |
|---|---|---|
| `0015_approval_consumed.sql` | statut `consumed` des approbations | **appliquée** (18/11) |
| `0016_agents.sql` | `agents`, `agent_capabilities`, `agent_runs`, `agent_messages`, RLS, contrainte anti-descente | préparée, **non appliquée** |

Aucune donnée existante n'est modifiée par `0016` : quatre tables sont créées, les politiques sont ajoutées.

---

## 7. Tests automatisés

| Test | Fichier | État |
|---|---|---|
| Chargement du package réel (17 agents) | `tests/test_agent_registry.py` | **12 tests passent** |
| Refus d'un modèle hors périmètre | idem | passe |
| Refus d'un spécialiste qui distribue | idem | passe |
| Refus d'un Core qui modifie les permissions | idem | passe |
| Refus d'un outil sans niveau d'approbation | idem | passe |
| Refus d'un outil sans statut | idem | passe |
| Refus du contournement RLS | idem | passe |
| Refus d'un délai hors bornes | idem | passe |
| Résultat sans preuve = non vérifié | idem | passe |
| Isolation croisée SQL | `tools/test_isolation_agents.sql` | à lancer après migration |
| Bout en bout multi-agents | à écrire avec le répartiteur | phase 2 |

---

## 8. Risques et rollback

| Risque | Mesure | Rollback |
|---|---|---|
| La migration 0016 échoue | script idempotent (`if not exists`), `ON_ERROR_STOP=1` en test | `drop table agent_messages, agent_runs, agent_capabilities, agents` |
| Le retrait de `DB_RLS_BYPASS` casse le worker | test croisé + 8 contrôles avant bascule | remettre la variable, redémarrer (30 s) |
| Un agent dépense trop | limites en unités, coût journalisé | désactiver l'agent (`status: retired`) |
| Un agent dépasse son domaine | registre + `may_execute_outside_domain: false` | retirer l'outil de la matrice |
| Régression sur le mono-agent | aucune modification du chemin existant avant la phase 5 | conserver le moteur actuel comme défaut |

---

## 9. Ce qui n'est pas fait

- Aucune migration appliquée, aucun service redémarré, aucun agent activé.
- Le répartiteur, le journal d'exécution alimenté et l'interface Missions restent à écrire.
- Les plafonds en euros restent `null` tant que tu n'as pas fourni le barème.
- Les 41 outils sans implémentation restent `declared` : ils ne sont jamais exposés au modèle.

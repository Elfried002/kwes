# KWES — Audit du package agentique V2

**Objet :** `KWES_AGENTIC_TEAM_CONFIG_V2.zip`
**Date :** 19 novembre 2026
**Auditeur :** Hermes (AEVIS), pour Elfried Yobouet
**Portée :** audit statique indépendant. Aucun agent activé, aucun service modifié, aucun secret touché.
**Empreinte du package audité :** 75 fichiers, 199 468 octets.

---

## 1. Méthode

1. Extraction et inventaire exhaustif (75 fichiers, arborescence vérifiée).
2. Contrôles statiques automatisés : structure, syntaxe YAML, unicité des identifiants, périmètre des modèles, vocabulaire des outils, graphe de collaboration, recherche de secrets.
3. Vérifications croisées : registre ↔ fichiers, configs ↔ `defaults.yaml`, configs ↔ `policy.yaml`, identités ↔ configurations.
4. Analyse de similarité des identités (shingles de 6 mots, tronc commun retiré puis conservé).
5. Comparaison avec l'état réel du moteur KWES (dépôt `business/kwes`, serveur de production).

Les scripts utilisés sont versionnés : `tools/audit_agentic_team.py`, et les contrôles croisés sont reproductibles (voir §7).

**Aucune conclusion de ce rapport ne repose sur une simple lecture de fichier** : chaque constat est adossé à un comptage, une comparaison ou une extraction.

---

## 2. Inventaire

```
kwes_agentic_team/
├── core/                       SOUL.md  AGENT.md  AGENT_SPEC.md  config.yaml
├── agents/<16 spécialistes>/   idem, 4 fichiers chacun
├── registry/agents.yaml        16 entrées, chemins vérifiés
├── shared/config/defaults.yaml paramètres communs
├── shared/config/policy.yaml   8 règles POL-001…POL-008, défaut = deny
├── shared/contracts/agent-result.schema.json
└── README.md  DECISIONS.md  CONFIGURATION_GUIDE.md
```

| Contrôle | Résultat |
|---|---|
| Agents détectés | **17** (KWES Core + 16 spécialistes) |
| Fichiers par agent | 4 / 4 pour les 17 — **aucun manquant** |
| Identifiants d'agent | 17, **tous uniques** |
| Entrées du registre | 16, chemins SOUL/AGENT/SPEC/config **tous existants** |
| Modèles cités dans les 17 configs | `gemini-3.8-live`, `gemini-3.8-live-extended-thinking` — **conforme** |
| Secrets détectés | **aucun** (pas de clé, jeton ou mot de passe en clair) |
| Syntaxe YAML | **valide** sur les 17 fichiers |

Le socle documentaire est propre : séparation claire entre identité (`SOUL`), procédure (`AGENT`), contrat détaillé (`AGENT_SPEC`) et paramètres (`config.yaml`), et les trois documents racine annoncent honnêtement `architecture_defined_not_deployed`.

---

## 3. Audit A — Identités et instructions

### 3.1 Ce qui est solide

- Chaque `SOUL.md` porte une identité, une mission, un caractère professionnel, un périmètre et des limites **propres à son domaine**. Hors tronc commun, la similarité maximale entre deux âmes est de **32 %** : les identités sont réellement distinctes.
- Tous les agents déclarent explicitement ne pas être souverains et recevoir leurs missions de KWES Core. Aucun fichier ne revendique l'orchestration, la modification de permissions ou le contournement de politique (recherche par expressions : `orchestr`, `délègue`, `modifie les permissions`, `contourne`, `débite`).
- Les 16 spécialistes déclarent `may_dispatch_agents: false`, `may_change_user_permissions: false`, `may_override_policy: false`, `may_execute_outside_domain: false`.
- Aucun bloc `delegation` dans les configs spécialistes : la contrainte « seul KWES Core distribue » est tenue au niveau des fichiers.

### 3.2 Ce qui pose problème

**AGT-004 — Les procédures opérationnelles sont des clones.** Les 16 `AGENT.md` ne diffèrent que par **8 lignes** (titre, périmètre, une limite propre, une liste de pairs). La procédure de mission, les critères de qualité et l'escalade sont identiques mot pour mot. Deux conséquences : un spécialiste « Vie quotidienne » applique la même méthode qu'un « Audit » ; et rien dans la procédure ne rappelle à l'agent *comment* exercer sa spécialité.

Extrait mesuré (research vs life) :

```
8 lignes différentes sur ~40
Sections identiques : Préparation · Exécution · Contrôles · Escalade · Livrable
```

**AGT-006 — Contradiction interne sur le statut des capacités.** `core/AGENT_SPEC.md` exige que chaque capacité soit marquée séparément `defined`, `implemented`, `tested`, `production`. Or **aucune** des 17 configurations ne porte un tel statut : `status` est unique et vaut `defined_not_activated`. Le document demande une chose que la configuration ne permet pas d'exprimer.

**AGT-012 — La politique de langue n'est pas répercutée.** KWES Core fixe `language_default: fr` et `user_language_detection: true` ; **aucun** des 16 `AGENT.md` ne mentionne la langue. Un agent peut donc répondre dans une autre langue que celle de l'utilisateur sans contredire sa propre procédure — exactement le défaut observé en production sur KWES.

---

## 4. Audit B — Configurations YAML

### 4.1 Structure

Les 17 fichiers partagent un jeu de clés cohérent : `agent_id`, `agent_type`, `authority`, `capabilities`, `collaboration`, `mission`, `model_policy`, `autonomy`, `execution`, `memory`, `safety`, `output`.

**AGT-008 — Deux schémas coexistent.** Core porte son identité dans un bloc `agent:` et ses niveaux dans `autonomy.levels` ; les spécialistes portent `agent_id` à la racine et `autonomy.supported_levels`. Un chargeur unique doit gérer deux formes, ce qui multiplie les cas d'erreur silencieuse.

**AGT-007 — Le registre ne sait pas charger Core.** `registry/agents.yaml` déclare `core: core` alors que `core/config.yaml` porte `agent_id: kwes.core`, et l'entrée Core ne fournit aucun chemin vers ses quatre fichiers. Un chargeur ne peut pas résoudre Core à partir du registre, alors que c'est l'agent dont tout dépend.

### 4.2 Héritage des paramètres communs

**AGT-003 — L'héritage n'existe pas.** `shared/config/defaults.yaml` définit les paramètres communs, mais **aucune** des 17 configurations ne le référence : le mot `defaults` n'apparaît dans aucun `config.yaml`. Résultat mesuré : **68 blocs redéclarés** (`model_policy`, `execution`, `memory`, `autonomy`, `safety`).

Le risque n'est pas cosmétique. Le jour où la politique d'approbation A3 évolue dans `defaults.yaml`, **les 17 agents conservent l'ancienne valeur** : une action externe pourrait rester autorisée alors que la politique globale l'interdit. C'est un défaut de sécurité par divergence silencieuse.

### 4.3 Capacités déclarées et permissions

**AGT-002 — 41 outils déclarés sur 54 n'ont aucune implémentation.** Le vocabulaire du package (`web.search`, `calendar.read`, `transaction.prepare`, `workflow.execute.authorized`…) ne correspond à rien dans le moteur. Correspondance réelle :

| Catégorie | Nombre |
|---|---|
| Outils déclarés (distincts) | 54 |
| Ont un équivalent dans le moteur KWES actuel | **13** |
| Sans aucune implémentation | **41** |

Exemples sans équivalent : `calendar.read` (personal), `transaction.prepare` (finance), `security.scan.authorized` (security), `image.generate.request` (vision), `workflow.execute.authorized` (automation).

Le `README` précise que ces outils sont des « permissions candidates » à relier au registre réel — c'est honnête, mais **rien dans la configuration ne distingue un outil candidat d'un outil disponible**, et `honest_capability_reporting: true` ne peut pas être appliqué sans cette distinction.

**AGT-005 — Aucune matrice outil → niveau d'autonomie.** Les spécialistes déclarent `supported_levels: [A0, A1, A2]` et deux clés pour A3/A4, mais **aucune configuration ne dit quel outil exige quel niveau**. Le moteur de politiques ne peut donc pas décider, pour un agent donné, si `document.create` est A1 ou A2.

**AGT-010 — Les outils de sécurité n'ont pas de périmètre structuré.** `security.scan.authorized` et `security.risk.report` supposent un périmètre d'actifs autorisés (POL-006). Le champ `scope` n'existe pas comme donnée de configuration : la règle est énoncée, mais elle n'est pas vérifiable automatiquement.

### 4.4 Paramètres inutiles, manquants, contradictoires

| Constat | Détail |
|---|---|
| Manquant | Budget de coût par agent (AGT-009) : Core annonce « sélection selon compétences, disponibilité, permissions et **coût** », aucune configuration ne porte de budget (1 seule mention de « budget » dans tout le package, et c'est un identifiant d'outil). |
| Manquant | Schéma JSON de validation des `config.yaml` (AGT-014) : seul le contrat de *sortie* est fourni. |
| Dupliqué | `status`, `product`, `environment` recopiés dans les 17 fichiers (AGT-011). |
| Incohérent | `registry.core: core` vs `agent_id: kwes.core` (AGT-007). |
| Ambigu | 50 relations de pairs asymétriques (`audit → research` existe, `research → audit` non) — ce n'est pas une erreur, mais rien ne l'explique (AGT-013). |

---

## 5. Audit C — Orchestration multi-agents

**Registre :** 16 entrées, identifiants conformes aux dossiers, aucun identifiant orphelin, aucun chemin cassé.

**Mécanismes prévus par Core** (crédibles et cohérents) : planification par DAG, exécution parallèle des tâches indépendantes, limites de concurrence (4), reprise, annulation, agrégation pondérée par les preuves, réconciliation en cas de conflit, audit obligatoire pour les impacts élevés.

**Contrat de délégation :** complet — `task_id`, `mission_id`, `agent_id`, `objective`, `expected_output`, `context_refs`, `constraints`, `allowed_tools`, `autonomy_level`, `deadline`, `resource_budget`, `dependencies`, `acceptance_criteria`. Un spécialiste ne choisit pas son autorité : le champ est fourni par Core.

**Garde-fous de boucle :** 3 échecs du même outil, 3 itérations sans progrès, arrêt sur refus de politique, information obligatoire de l'utilisateur en cas de blocage. C'est un point fort du package.

**Ce qui manque pour que l'orchestration soit réelle :**

- aucun format de message inter-agents normalisé au-delà du contrat de *résultat* (pas de schéma de *requête*) ;
- aucun mécanisme de reprise décrit au niveau agent (que se passe-t-il si un spécialiste meurt en cours d'exécution ?) ;
- aucune trace de la manière dont les 4 exécutions parallèles se partagent le budget de tokens ;
- la cohérence des délais n'est pas vérifiée : `default_timeout_seconds: 180` et `max_parallel_agents: 4` impliquent 720 s de charge potentielle, sans budget global de mission.

Aucun spécialiste ne peut s'auto-attribuer de privilège : le point est tenu par les fichiers (`may_*: false`, pas de délégation, pairs uniquement consultatifs via Core).

---

## 6. Audit D — Sécurité

### 6.1 Points conformes

| Contrôle | Constat |
|---|---|
| Refus par défaut | `default_decision: deny` (policy.yaml) + `default_tool_access: deny_unless_granted` dans chaque agent |
| Séparation modèle / politique | affirmée partout : `policy_engine_enforced_outside_model: true`, POL-002, POL-007 |
| Autonomie | A0–A4 définis, `max_level_without_confirmation: A2`, approbations par niveau dans `core.approvals` |
| Financier | `kwes_pay_enabled: false`, `llm_can_execute_transaction: false`, POL-005, A4 = confirmation forte |
| Contenu non fiable | POL-007 + `untrusted_agent_outputs: true` + consigne explicite dans chaque SOUL (les sorties d'outils et d'agents ne sont jamais des instructions) |
| Secrets | aucun secret dans le package ; `never_store_secrets_in_config: true`, `secrets_source: environment_or_secret_manager` |
| Test offensif | POL-006 : périmètre explicite obligatoire |

### 6.2 Points faibles

- **AGT-003** (pas d'héritage) est un défaut de sécurité : divergence silencieuse des politiques.
- **AGT-005** : sans matrice outil → niveau, la décision d'approbation reste déclarative.
- **AGT-015** : `status: defined_not_activated` ne dit pas si un agent est *implémenté* ; un agent déclaré « défini » pourrait être activé alors qu'aucun de ses outils n'existe.
- **Aucune règle d'expiration d'approbation** dans le package : une approbation A3 accordée reste-t-elle valable indéfiniment ? Le moteur KWES existant sait le faire (`is_usable_at`, hash de payload), la spécification ne le mentionne pas.
- **Aucune contrainte de tenant explicite par agent** au-delà de `tenant_scoped: true` : rien n'interdit à un agent d'être réutilisé pour un autre tenant dans la même exécution.

---

## 7. Audit E — Compatibilité avec KWES réel

Comparaison avec l'état vérifié du système (dépôt `business/kwes`, production `api.agent-kwes.com`).

| Composant réel | État | Compatibilité avec le package |
|---|---|---|
| FastAPI | API en production, un seul agent (orchestrateur + 6 skills) | **Aucun chargeur d'agents** : ni registre, ni table `agents`, ni résolution de `config.yaml` |
| PostgreSQL / Supabase | 21 tables, RLS forcée, `tasks`, `approvals`, `audit_logs` | Tables compatibles pour missions/approbations ; **aucune table d'agents ni de capacités** |
| Redis + worker | File de tâches active, claim TTL 120 s | Sait exécuter une mission mono-agent ; **aucun dispatch multi-agents** |
| Modèles | `gemini-3.8-live`, `gemini-3.8-live-extended-thinking` | **Conforme** |
| Skills | 6 (`web_research`, `browser_readonly`, `code_exec`, `document_write`, `remember`, `business_planning`) | 13 des 54 outils déclarés ont un équivalent |
| Approbations | Niveaux R1–R4, table `approvals`, hash de payload | **Vocabulaire différent** (R1–R4 vs A0–A4) : table de correspondance absente |
| RLS multi-tenant | Politiques actives, API via `kwes_app` | **Le worker contourne la RLS** (`DB_RLS_BYPASS`) : si les agents y tournent, l'isolation repose sur le code applicatif |
| Voix Gemini Live | Opérationnelle | Compatible (Core déclare `voice_chat_mode: live`) |
| PWA / Vercel / VPS | En production | Sans objet pour les agents |

**Conclusion de compatibilité :** le package est *conceptuellement* aligné sur KWES (mêmes modèles, même source de vérité, même refus par défaut), mais **aucun de ses objets n'est chargeable par le moteur actuel**. Il manque trois briques : un registre d'agents persistant, un chargeur/validateur de configuration, et un orchestrateur capable de distribuer des contrats de tâche.

---

## 8. Vérification de la proposition V3 par le harnais

Les corrections documentaires ont été appliquées dans `KWES_AGENTIC_TEAM_CONFIG_V3/` (identités laissées intactes, empreintes SHA-256 comparées), puis le même harnais a été relancé sur les deux versions :

| Contrôle | V2 | V3 |
|---|---|---|
| Configurations valides | 17 / 17 | 17 / 17 |
| Anomalies ÉLEVÉ | **31** | **16** |
| dont procédures clonées (AGT-004) | 16 | 16 *(volontairement non corrigé)* |
| dont outils présentés comme disponibles sans implémentation (AGT-002) | 15 | **0** |
| Anomalies MOYEN | 0 | 15 |
| Identités modifiées | — | **aucune** |
| Modèles hors périmètre | 0 | 0 |

Autrement dit : la V3 supprime la classe d'anomalie « fausse capacité » (les 41 outils sans implémentation sont désormais explicitement marqués `declared`, donc suivis comme feuille de route et jamais exposés au modèle) et conserve les 16 procédures clonées, qui touchent aux identités et exigent une décision d'Elfried.

Résultats machine : `docs/audit/audit_v2.json` et `docs/audit/audit_v3.json`.

## 9. Verdict

**VALIDÉ SOUS RÉSERVE.**

Le package est cohérent, prudent et honnête sur son propre statut : identités distinctes, refus par défaut, séparation modèle/politique, aucun secret, aucun agent ne s'arroge de privilège. C'est une base saine.

Il n'est **pas intégrable en l'état**, pour trois raisons bloquantes :

1. **AGT-001** — rien dans le moteur ne sait charger ce package ;
2. **AGT-002** — 41 des 54 outils déclarés n'existent pas ;
3. **AGT-003** — l'héritage des paramètres communs est absent, donc les politiques divergeront silencieusement.

Et deux réserves de qualité : les procédures `AGENT.md` sont des clones (AGT-004), et la matrice outil → autonomie manque (AGT-005).

Le détail, la classification et les corrections sont dans les trois documents joints ; une proposition de package V3 corrigé accompagne ce rapport, sans modifier la V2.

# KWES — Anomalies du package agentique V2

**Date :** 19 novembre 2026
**Source :** `KWES_AGENTIC_TEAM_CONFIG_V2.zip` (75 fichiers, 199 468 octets)
**Rappel :** chaque anomalie a été constatée par comptage ou comparaison, pas par lecture rapide.

Classification : **CRITIQUE** (empêche l'intégration ou crée un risque de sécurité), **ÉLEVÉ** (défaut fonctionnel réel), **MOYEN** (dette ou ambiguïté), **FAIBLE** (forme).

| ID | Niveau | Contrôle | Fichier(s) |
|---|---|---|---|
| AGT-001 | CRITIQUE | Intégration | moteur KWES |
| AGT-002 | CRITIQUE | Capacités | 16 `config.yaml` |
| AGT-003 | CRITIQUE | Héritage / sécurité | 17 `config.yaml` |
| AGT-004 | ÉLEVÉ | Identités | 16 `AGENT.md` |
| AGT-005 | ÉLEVÉ | Sécurité | 16 `config.yaml` |
| AGT-006 | ÉLEVÉ | Cohérence | `core/AGENT_SPEC.md` |
| AGT-007 | ÉLEVÉ | Registre | `registry/agents.yaml` |
| AGT-008 | ÉLEVÉ | Schéma | `core/config.yaml` |
| AGT-009 | ÉLEVÉ | Coût | 17 `config.yaml` |
| AGT-010 | ÉLEVÉ | Sécurité | `agents/security/config.yaml` |
| AGT-011 | MOYEN | Maintenance | 17 `config.yaml` |
| AGT-012 | MOYEN | Langue | 16 `AGENT.md` |
| AGT-013 | MOYEN | Collaboration | 16 `config.yaml` |
| AGT-014 | MOYEN | Validation | package |
| AGT-015 | MOYEN | Traçabilité | 17 `config.yaml` |
| AGT-016 | MOYEN | Documentation | `README.md` |
| AGT-017 | FAIBLE | Forme | tous |
| AGT-018 | FAIBLE | Distribution | package |
| AGT-019 | ÉLEVÉ | Isolation | moteur KWES (worker) |

---

## CRITIQUE

### AGT-001 — Aucun point de chargement dans le moteur KWES

**Fichier :** hors package — `business/kwes/backend/app/*`
**Constat :** le moteur n'a ni registre d'agents persistant, ni chargeur de `config.yaml`, ni schéma Pydantic d'agent, ni orchestrateur multi-agents. `registry/agents.yaml` n'est lu par aucun composant. Les tables `tasks`, `approvals`, `audit_logs` existent, mais aucune table `agents` ni `agent_capabilities`.
**Risque :** le package ne peut pas être activé, même partiellement. Toute promesse d'« intégration » sans cette brique serait fausse.
**Correction :** implémenter, avant toute activation : `agents` + `agent_capabilities` (tenant-scoped), un schéma Pydantic strict, un chargeur qui refuse un agent invalide, et un répartiteur qui transforme un plan en contrats de tâche.

### AGT-002 — 41 outils déclarés sans implémentation

**Fichiers :** les 16 `agents/*/config.yaml`, bloc `capabilities.declared_tool_ids`
**Constat :** 54 identifiants distincts ; **13** seulement correspondent à un skill réel (`web.search`→`web_research`, `web.page.read`→`browser_readonly`, `document.create`→`document_write`, etc.) ; **41** n'ont aucun équivalent, dont `calendar.read`, `transaction.prepare`, `security.scan.authorized`, `image.generate.request`, `workflow.execute.authorized`.
**Risque :** un agent annoncerait une capacité inexistante — exactement ce que le référentiel interdit (« ne jamais annoncer une capacité non opérationnelle »). Avec `honest_capability_reporting: true`, la configuration se contredit elle-même.
**Correction :** ajouter un statut par outil (`declared` / `implemented` / `tested`), refuser au chargement un agent dont un outil est `declared` mais non implémenté, et n'exposer au modèle que les outils effectivement enregistrés.

### AGT-003 — L'héritage des paramètres communs n'existe pas

**Fichiers :** les 17 `config.yaml` ; `shared/config/defaults.yaml`
**Constat :** **aucune** configuration ne référence `defaults.yaml` (le mot est absent des 17 fichiers) ; **68 blocs** sont redéclarés à l'identique (`model_policy`, `execution`, `memory`, `autonomy`, `safety`).
**Risque :** le jour où la politique change dans `defaults.yaml`, les agents conservent l'ancienne valeur. Une approbation A3 supprimée au niveau global resterait exigée ailleurs — ou l'inverse : une action externe resterait permise. Divergence silencieuse, non détectable sans diff manuel.
**Correction :** introduire une clé `inherits: shared/config/defaults.yaml`, ne garder dans chaque fichier que les surcharges explicites, et faire échouer le chargement si un bloc dupliqué diffère des valeurs héritées sans être déclaré en `overrides`.

---

## ÉLEVÉ

### AGT-004 — Procédures opérationnelles clonées

**Fichiers :** les 16 `agents/*/AGENT.md`
**Constat :** deux fichiers comparés (research, life) diffèrent par **8 lignes** sur ~40 ; la préparation, l'exécution, les contrôles, l'escalade et le livrable sont identiques. Hors tronc commun, la similarité reste de **65 à 70 %**.
**Risque :** tous les spécialistes travaillent selon la même méthode ; la spécialisation n'existe que dans le vocabulaire. Un agent « Audit » n'a aucune procédure de contrôle indépendante propre, un agent « Finance » aucune procédure de rapprochement.
**Correction :** rédiger, par domaine, 3 à 5 étapes réellement spécifiques (méthode, sources autorisées, critères de qualité, mode d'échec). Conserver le tronc commun comme inclusion, pas comme corps du fichier.

### AGT-005 — Aucune matrice outil → niveau d'autonomie

**Fichiers :** les 16 `agents/*/config.yaml`, bloc `autonomy`
**Constat :** `supported_levels: [A0, A1, A2]` + deux clés A3/A4, mais **aucune** association outil → niveau. Le moteur ne peut pas décider si `document.create` est A1 ou A2, ni si `workflow.execute.authorized` exige A3.
**Risque :** la décision d'approbation reste déclarative ; deux agents peuvent classer la même action différemment.
**Correction :** ajouter `approval_matrix` : pour chaque outil déclaré, le niveau minimal et l'exigence d'approbation. Le moteur applique cette matrice, pas le modèle.

### AGT-006 — Le statut par capacité exigé n'est jamais fourni

**Fichiers :** `core/AGENT_SPEC.md` § « État de livraison » vs les 17 `config.yaml`
**Constat :** la spécification exige que chaque capacité soit marquée `defined`, `implemented`, `tested`, `production`. Aucune configuration ne porte un tel champ (0/17).
**Risque :** l'exigence la plus importante du document (ne pas confondre défini et opérationnel) n'est pas applicable.
**Correction :** même correction qu'AGT-002 : un statut par capacité, et un refus d'activation si le statut n'est pas `tested`.

### AGT-007 — Le registre ne sait pas charger KWES Core

**Fichier :** `registry/agents.yaml`
**Constat :** `core: core` alors que `core/config.yaml` déclare `agent_id: kwes.core` ; l'entrée Core ne donne aucun chemin vers ses quatre fichiers, contrairement aux 16 spécialistes.
**Risque :** un chargeur qui suit le registre ne trouve pas l'orchestrateur.
**Correction :** remplacer par une entrée complète `agent_id: kwes.core` avec `config`, `soul`, `agent`, `spec`.

### AGT-008 — Deux schémas de configuration coexistent

**Fichiers :** `core/config.yaml` vs les 16 `agents/*/config.yaml`
**Constat :** Core imbrique son identité dans `agent:` et ses niveaux dans `autonomy.levels` ; les spécialistes portent `agent_id` à la racine et `autonomy.supported_levels`. Les clés d'autorité diffèrent aussi (`authority: central_orchestrator` vs bloc `authority:` à quatre booléens).
**Risque :** deux chemins de code, deux jeux de tests, erreurs silencieuses à la lecture.
**Correction :** un schéma unique ; les différences de rôle passent par des champs, pas par une forme différente.

### AGT-009 — Aucun budget de coût par agent

**Fichiers :** les 17 `config.yaml`, bloc `execution`
**Constat :** délai (180 s) et tentatives (2) sont définis ; aucun budget de tokens, d'appels ou d'euros. Core annonce pourtant une sélection « selon compétences, disponibilité, permissions et **coût** ».
**Risque :** 4 agents en parallèle × 180 s sans plafond de coût ; la sélection par coût est impossible.
**Correction :** `budget: {max_tokens_per_task, max_tool_calls, max_cost_eur}` par agent, et un budget de mission agrégé dans Core.

### AGT-010 — Outils de sécurité sans périmètre structuré

**Fichier :** `agents/security/config.yaml`
**Constat :** `security.scan.authorized` et `security.risk.report` supposent des actifs explicitement autorisés (POL-006), mais aucun champ `scope`/`authorized_assets` n'existe.
**Risque :** un scan pourrait viser un actif hors périmètre sans que le moteur puisse le détecter.
**Correction :** `scope: {authorized_assets: [], requires_owner_signature: true}` et refus si la cible n'est pas dans la liste.

### AGT-019 — L'exécution des agents contournerait la RLS

**Fichier :** hors package — `kwes-worker.service` (`DB_RLS_BYPASS=true`)
**Constat :** l'API applique la RLS via `kwes_app` + claims ; le worker, lui, se connecte avec le rôle propriétaire pour traiter toutes les missions. Si les agents s'exécutent dans le worker, aucune politique de base ne les arrête.
**Risque :** une erreur de filtre `tenant_id` dans un agent donnerait accès aux données d'un autre espace, sans filet de sécurité.
**Correction :** exécuter les agents avec le rôle applicatif et un contexte posé par tâche (comme l'API), ou réintroduire une vérification applicative systématique du tenant sur chaque lecture/écriture, testée par un cas croisé.

---

## MOYEN

### AGT-011 — Duplication des blocs communs
**Fichiers :** 17 `config.yaml` · **Constat :** 68 blocs dupliqués · **Risque :** maintenance et dérive (même cause qu'AGT-003, conséquence distincte) · **Correction :** héritage + surcharges.

### AGT-012 — Politique de langue non répercutée
**Fichiers :** 16 `AGENT.md` · **Constat :** 0/16 mentionne la langue, alors que Core impose `fr` par défaut avec détection · **Risque :** réponses dans une autre langue, défaut déjà observé en production · **Correction :** ajouter une règle de langue courte dans le tronc commun des procédures.

### AGT-013 — Relations de pairs asymétriques
**Fichiers :** 16 `config.yaml`, `collaboration.permitted_peers` · **Constat :** 50 paires sans réciprocité (`audit → research` existe, l'inverse non) · **Risque :** ambiguïté sur la consultation mutuelle ; ce n'est pas une erreur de sécurité puisque tout passe par Core · **Correction :** documenter le sens (contributeur potentiel, pas réciprocité) ou rendre les listes symétriques.

### AGT-014 — Aucun schéma de validation des configurations
**Fichier :** package · **Constat :** `shared/contracts/agent-result.schema.json` existe pour la sortie, aucun schéma JSON pour les `config.yaml` · **Risque :** une clé mal orthographiée passe silencieusement · **Correction :** `shared/contracts/agent-config.schema.json` + validation au chargement.

### AGT-015 — Traçabilité de version insuffisante
**Fichiers :** 17 `config.yaml` · **Constat :** `version: 1.0.0` et `status: defined_not_activated` identiques partout, sans date ni auteur · **Risque :** impossible de savoir quelle version de quel agent tourne · **Correction :** `version`, `updated_at`, `owner`, `changelog` par agent.

### AGT-016 — Correspondance package ↔ moteur absente de la documentation
**Fichier :** `README.md` · **Constat :** la liste des 16 agents est donnée sans table de correspondance vers les skills réels · **Risque :** l'intégrateur doit deviner · **Correction :** table `agent → outils déclarés → skill réel → statut`.

---

## FAIBLE

### AGT-017 — Mélange de conventions
Clés majoritairement en anglais, valeurs en français, quelques identifiants en français (`evidence.inspect` est anglais, `business.kpi.read` aussi, mais les domaines sont en français). Sans impact technique ; à normaliser avant industrialisation.

### AGT-018 — Pas de LICENSE ni de CHANGELOG
Le package circule sans cadre d'utilisation ni historique. À ajouter avant diffusion externe.

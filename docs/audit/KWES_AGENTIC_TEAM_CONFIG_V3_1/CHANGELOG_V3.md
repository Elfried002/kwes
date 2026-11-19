# KWES Agentic Team — Configuration V3 (proposition)

**Dérivée de :** `KWES_AGENTIC_TEAM_CONFIG_V2.zip`
**Date :** 19 novembre 2026
**Nature :** proposition de correction. La V2 originale n'est ni remplacée ni supprimée.

---

## 1. Ce qui n'a pas changé — volontairement

| Élément | État |
|---|---|
| `SOUL.md`, `AGENT.md`, `AGENT_SPEC.md` (17 × 3 = 51 fichiers) | **identiques au bit près** (empreintes SHA-256 comparées après génération) |
| Identifiants et périmètres des 16 spécialistes | inchangés |
| Modèles autorisés | `gemini-3.8-live`, `gemini-3.8-live-extended-thinking` uniquement |
| Aucun agent supprimé, fusionné ou renommé | conforme à la consigne |
| Aucun secret ajouté | le package n'en contient toujours aucun |

## 2. Corrections appliquées

| Anomalie | Correction | Fichiers |
|---|---|---|
| **AGT-007** registre incapable de charger Core | entrée `core` complète : `agent_id: kwes.core` + chemins des quatre fichiers | `registry/agents.yaml` |
| **AGT-008** deux schémas coexistent | Core aligné sur le schéma des spécialistes : `agent_id` au premier niveau, bloc `agent:` supprimé, `autonomy.supported_levels` | `core/config.yaml` |
| **AGT-003 / AGT-011** aucun héritage, 68 blocs dupliqués | `inherits: shared/config/defaults.yaml` + `overrides: []` dans les 17 fichiers ; **36 blocs identiques retirés** (`product`, `environment`, `status`, `memory`, `safety`, `model_policy` selon les cas) | 17 `config.yaml` |
| **AGT-002 / AGT-006** capacités non distinguées | `capabilities.tool_status` : `implemented` pour les 13 outils réellement disponibles, `declared` pour les 41 autres, plus la règle `runtime_rule` | 16 `config.yaml` |
| **AGT-005** aucune matrice d'approbation | `approval_matrix` : un niveau et une exigence d'approbation par outil déclaré | 16 `config.yaml` |
| **AGT-009** aucun budget | `execution.budget` avec `max_tool_calls: 12` et deux valeurs `null` à trancher par le propriétaire | 17 `config.yaml` |
| **AGT-010** scan sans périmètre | bloc `scope` avec liste d'actifs vide, signature du propriétaire obligatoire et refus hors périmètre | `agents/security/config.yaml` |
| **AGT-014** pas de schéma de validation | `shared/contracts/agent-config.schema.json` (validation stricte : motif d'identifiant, types, bornes de délai et de tentatives) | nouveau fichier |
| **AGT-015** traçabilité insuffisante | `version: 1.1.0`, `updated_at: 2026-11-19`, `owner` | 17 `config.yaml` |

### Règle d'approbation appliquée (à relire par le propriétaire)

- **A0, aucune approbation** : lecture, recherche, analyse, extraction d'un document, vérification.
- **A1, aucune approbation** : brouillon, plan, rapport, synthèse, proposition.
- **A2, contrôle de politique** : exécution de code dans l'espace de travail, tests.
- **A3, approbation explicite** : exécution de workflow, scan de sécurité autorisé, préparation de transaction, génération d'image, déploiement.

Cette matrice est volontairement conservatrice : toute action à effet externe est classée A3.

## 3. Corrections proposées mais non appliquées — **[À VALIDER]**

Elles touchent aux identités ou à des décisions qui vous appartiennent :

1. **AGT-004** — rédiger 4 sections propres à chaque métier dans les 16 `AGENT.md` (méthode, sources autorisées, critères de qualité, modes d'échec). Aujourd'hui, 8 lignes seulement distinguent deux agents.
2. **AGT-012** — ajouter la règle de langue au tronc commun des `SOUL.md` (réponse dans la langue de la dernière réplique, français par défaut).
3. **AGT-009** — fixer les plafonds réels (`max_tokens_per_task`, `max_cost_eur`).
4. **AGT-019** — choisir le mode d'isolation d'exécution : rôle applicatif avec contexte par tâche (recommandé) ou vérification applicative du tenant avec test croisé obligatoire.

## 4. Vérifications effectuées sur la V3

```
configs valides            : 17 / 17
identités modifiées        : aucune (SHA-256 comparés)
modèles hors périmètre     : aucun
configs sans inherits      : aucune
configs sans tool_status   : aucune (16/16 spécialistes)
configs sans matrice       : aucune (16/16 spécialistes)
```

## 5. Ce que la V3 ne fait pas

La V3 corrige la **cohérence documentaire et la politique déclarée**. Elle ne rend pas les agents exécutables : il manque toujours, côté moteur, le registre persistant, le chargeur, le répartiteur de tâches et le journal par agent (AGT-001). Aucun agent n'est activé par ce package.

## 6. Procédure de validation proposée

1. Relire `approval_matrix` sur les 16 agents et corriger les niveaux contestés.
2. Trancher les quatre points **[À VALIDER]**.
3. Implémenter le chargeur + le schéma JSON côté moteur, puis charger la V3 en mode « dry-run » (aucune exécution).
4. Charger les 17 agents et vérifier : 17 chargés, 0 erreur, 0 outil `declared` exposé.
5. Seulement ensuite, activation progressive d'un agent pilote (`research`), avec preuve d'exécution.

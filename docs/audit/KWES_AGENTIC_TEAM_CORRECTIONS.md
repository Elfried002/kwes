# KWES — Corrections recommandées (package agentique V2)

**Date :** 19 novembre 2026
**Principe :** aucune correction n'altère une identité (`SOUL.md`), ne fusionne un agent, ni ne change un modèle. Les propositions ci-dessous sont classées par fichier et renvoient aux anomalies du document `KWES_AGENTIC_TEAM_ISSUES.md`.

Ces corrections sont **appliquées** dans la proposition `KWES_AGENTIC_TEAM_CONFIG_V3/` (voir `CHANGELOG_V3.md`), sauf celles marquées **[À VALIDER]** qui demandent une décision d'Elfried.

---

## 1. `registry/agents.yaml`

**Anomalie :** AGT-007
**Correction :** remplacer `core: core` par une entrée complète, cohérente avec les 16 autres.

```yaml
core:
  agent_id: kwes.core
  slug: core
  name: KWES
  domain: Orchestration centrale
  config: core/config.yaml
  soul: core/SOUL.md
  agent: core/AGENT.md
  spec: core/AGENT_SPEC.md
  status: defined_not_activated
```

## 2. Les 17 `config.yaml` — héritage

**Anomalie :** AGT-003, AGT-011
**Correction :** chaque fichier déclare son héritage et ne conserve que ses différences.

```yaml
inherits: shared/config/defaults.yaml
overrides:
  - model_policy        # uniquement si la valeur diffère réellement
  - execution
```

Les blocs `product`, `environment`, `status`, `model_policy`, `memory`, `safety` sont retirés des fichiers agents lorsqu'ils sont identiques à `defaults.yaml`. Le chargeur doit refuser un fichier qui redéclare un bloc hérité sans le lister dans `overrides`.

## 3. Les 17 `config.yaml` — statut par capacité

**Anomalies :** AGT-002, AGT-006
**Correction :** distinguer l'outil *candidat* de l'outil *disponible*.

```yaml
capabilities:
  declared_tool_ids:
    - web.search
  tool_status:
    web.search: implemented      # implemented | declared
    research.synthesis: declared
  runtime_requirement: "un outil `declared` n'est jamais exposé au modèle"
```

Règle d'activation : un agent dont un outil déclaré est utilisé dans un plan doit être refusé si `tool_status` vaut `declared`.

## 4. Les 16 `config.yaml` — matrice d'approbation

**Anomalie :** AGT-005
**Correction :** associer chaque outil à un niveau et à une exigence d'approbation.

```yaml
approval_matrix:
  web.search:                {level: A0, approval: none}
  document.create:           {level: A1, approval: none}
  document.extract:          {level: A1, approval: none}
  message.draft:             {level: A1, approval: none}
  workflow.execute.authorized: {level: A3, approval: explicit}
  transaction.prepare:       {level: A3, approval: explicit}
```

Le moteur applique cette matrice ; le modèle ne la voit jamais.

## 5. Les 16 `config.yaml` — budget

**Anomalie :** AGT-009
**Correction :** ajouter un budget **explicite**, sans inventer de montant.

```yaml
execution:
  timeout_seconds: 180
  max_retries: 2
  budget:
    max_tokens_per_task: null      # [À VALIDER] valeur à fixer par le propriétaire
    max_tool_calls: 12
    max_cost_eur: null             # [À VALIDER]
```

Tant que les valeurs sont `null`, le moteur doit appliquer les plafonds globaux de Core et le signaler dans la trace.

## 6. `agents/security/config.yaml` — périmètre

**Anomalie :** AGT-010
**Correction :**

```yaml
scope:
  authorized_assets: []            # obligatoire avant tout scan
  requires_owner_signature: true
  out_of_scope_behavior: refuse
```

## 7. `core/config.yaml` — schéma unifié

**Anomalie :** AGT-008
**Correction :** déplacer l'identité de Core au même niveau que les spécialistes.

```yaml
agent_id: kwes.core
display_name: KWES
agent_type: orchestrator
authority:
  may_dispatch_agents: true
  may_change_user_permissions: true
  may_override_policy: false       # le moteur de politiques reste au-dessus
  may_execute_outside_domain: true
autonomy:
  supported_levels: [A0, A1, A2, A3, A4]
```

Le bloc `agent:` disparaît. Les clés `orchestration`, `delegation`, `voice`, `channels` restent spécifiques à Core et sont documentées comme telles.

## 8. `shared/contracts/agent-config.schema.json` (nouveau)

**Anomalie :** AGT-014
**Correction :** publier un schéma JSON strict, validé au chargement : `agent_id` (motif `^kwes\.[a-z]+$`), `agent_type` (`orchestrator|specialist`), `authority` (4 booléens), `capabilities` (liste + statut), `approval_matrix` (couverture obligatoire de tous les outils déclarés), `execution` (timeout ≤ 600, retries ≤ 3), `model_policy` (modèles autorisés uniquement).

## 9. Les 16 `AGENT.md` — procédures propres

**Anomalie :** AGT-004 **[À VALIDER]**
**Correction proposée :** conserver le tronc commun en fin de fichier, et rédiger au-dessus 4 sections réellement spécifiques :

```
## Méthode du domaine        (3 à 6 étapes propres au métier)
## Sources et outils autorisés
## Critères de qualité vérifiables
## Modes d'échec et escalade propres au domaine
```

Exemples attendus : pour `audit`, une procédure d'échantillonnage et de contre-vérification ; pour `finance`, un rapprochement obligatoire avant tout chiffre publié ; pour `security`, une vérification de périmètre avant action.

Cette correction touche au contenu des identités opérationnelles : **elle n'est pas appliquée dans la V3**, elle est proposée pour validation.

## 10. Tronc commun — règle de langue

**Anomalie :** AGT-012 **[À VALIDER]**
**Correction proposée :** ajouter une puce au tronc commun des `SOUL.md` (et non au corps spécifique) :

> Tu réponds dans la langue de la dernière réplique de l'utilisateur (français ou anglais). Tu ne mélanges jamais deux langues, pas même un mot. Dans toute autre langue, tu réponds en français.

Non appliquée en V3 : elle modifie les identités, donc hors du périmètre autorisé sans validation.

## 11. Isolation d'exécution

**Anomalie :** AGT-019
**Correction :** deux options, à trancher avant activation.

- **Option A (recommandée)** : exécuter les agents avec le rôle `kwes_app` et un contexte RLS posé par tâche, comme l'API.
- **Option B** : conserver le rôle propriétaire pour le worker, mais imposer une vérification applicative du tenant sur chaque accès, couverte par un test croisé obligatoire (deux tenants, tentative de lecture croisée).

## 12. Documentation

**Anomalies :** AGT-013, AGT-016, AGT-018
**Corrections :** table de correspondance `agent → outils → skill réel → statut` dans le README ; note sur le sens des `permitted_peers` ; ajout d'un `CHANGELOG.md` et d'une licence.

---

## Ordre d'application recommandé

1. **Semaine 1** — AGT-001 (registre + chargeur + schéma), AGT-003 (héritage), AGT-007, AGT-008 : sans cela, rien ne se charge.
2. **Semaine 1** — AGT-002 et AGT-006 (statut par capacité) : évite d'annoncer des outils inexistants.
3. **Semaine 2** — AGT-005 (matrice d'approbation) et AGT-019 (isolation) : ce sont les deux corrections qui ont un effet direct sur la sécurité.
4. **Semaine 2** — AGT-004 (procédures) et AGT-012 (langue) : qualité et cohérence produit.
5. **Ensuite** — AGT-009, AGT-010, AGT-014, AGT-015, AGT-016, AGT-017, AGT-018.

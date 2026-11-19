# KWES — Compatibilité du package agentique V2 avec le système réel

**Date :** 19 novembre 2026
**Méthode :** comparaison entre les objets déclarés dans le package et l'état vérifié du moteur en production (`api.agent-kwes.com`, serveur `185.181.122.118`, dépôt `business/kwes`).
**Règle appliquée :** une intégration n'est jamais considérée opérationnelle parce qu'elle est déclarée dans un fichier.

---

## 1. État réel du moteur (constaté)

| Composant | Réalité vérifiée |
|---|---|
| API | FastAPI, service `kwes-api`, `https://api.agent-kwes.com/api/v1`, santé 200 |
| Orchestrateur | **mono-agent** : un planificateur, 6 skills, un worker |
| Skills installés | `web_research`, `browser_readonly`, `code_exec`, `document_write`, `remember`, `business_planning` |
| Base | PostgreSQL 16, 21 tables publiques, RLS forcée |
| Tables disponibles | `tasks`, `task_steps`, `executions`, `approvals`, `audit_logs`, `documents`, `evidence`, `memories`, `messages`, `conversations`, `integrations`, `notifications`, `voice_sessions`, `device_connectors`, `device_commands`, `tenants`, `tenant_memberships`, `tenant_settings`, `profiles`, `skills`, `skill_versions` |
| File de tâches | Redis, claim TTL 120 s, sweep 30 s, file `kwes:queue:tasks` |
| Worker | service `kwes-worker`, exécution du code sous `kwesexec`, **`DB_RLS_BYPASS=true`** |
| Politique | moteur R1–R4 (`app/agent/policy.py`), refus R3/R4, approbation R2, hash de payload |
| Modèles | `gemini-3.8-live`, `gemini-3.8-live-extended-thinking` |
| Voix | Gemini Live, une voix, barge-in, narration d'outil |
| Frontend | React/Vite PWA sur Vercel, API HTTPS sur VPS |

Aucune table `agents`, `agent_capabilities`, `agent_runs` ou `agent_messages` n'existe.

---

## 2. Correspondance des outils

Le package déclare **54** identifiants d'outils distincts. **13** ont un équivalent réel :

| Outil déclaré | Skill réel | Agents concernés |
|---|---|---|
| `web.search` | `web_research` | research, sales, marketing, business, life, relationship… |
| `research.synthesis` | `web_research` | research |
| `source.citation` | `web_research` | research |
| `local.info.research` | `web_research` | life |
| `service.compare` | `web_research` | life |
| `lead.research` | `web_research` | sales |
| `web.page.read` | `browser_readonly` | research, documents, automation |
| `code.read` | `code_exec` | tech |
| `code.write.workspace` | `code_exec` | tech |
| `test.run.sandbox` | `code_exec` | tech |
| `document.create` | `document_write` | documents, business, marketing, relation |
| `profile.preference.read` | `remember` | personal |
| `business.planning` | `business_planning` | business |

**41 outils n'ont aucun équivalent**, dont les plus structurants :

| Domaine | Outils sans implémentation |
|---|---|
| Personnel | `calendar.read`, `task.manage`, `reminder.propose` |
| Finance | `finance.analysis`, `budget.read.authorized`, `transaction.prepare` |
| Sécurité | `security.logs.read`, `security.scan.authorized`, `security.config.audit`, `security.risk.report` |
| Documents | `document.read`, `document.extract`, `document.convert` |
| Vision | `image.analyze`, `image.generate.request`, `visual.quality_review` |
| Automatisation | `workflow.design`, `workflow.validate`, `workflow.execute.authorized` |
| Vente / relation | `sales.pipeline.read`, `sales.proposal.draft`, `message.draft`, `support.response.draft` |
| Business | `business.analysis`, `business.kpi.read`, `business.report.create` |
| Opérations | `operations.plan`, `inventory.read.authorized`, `order.status.read` |
| Audit / qualité | `result.verify`, `evidence.inspect`, `quality.audit` |
| Apprentissage | `learning.plan`, `learning.explain`, `learning.assess` |
| Marketing | `marketing.strategy`, `content.draft`, `seo.audit` |
| Divers | `deployment.prepare`, `customer.context.read.authorized`, `daily.planning` |

---

## 3. Correspondance des niveaux de risque

Le package raisonne en **A0–A4** ; le moteur en **R1–R4**. Aucune table de correspondance n'existe.

| Package | Moteur (réel) | Conséquence |
|---|---|---|
| A0 consultation | R0/R1 | lecture, exécution interne : compatible |
| A1 préparation | R1 | brouillon, document : compatible |
| A2 action réversible | R1/R2 | selon l'outil ; la correspondance n'est pas automatique |
| A3 action externe | R2 | le moteur exige déjà une approbation avec hash de payload |
| A4 financier/critique | R3/R4 | **le moteur refuse purement R3/R4** : cohérent avec KWES Pay désactivé |

Sans table de correspondance, un agent A3 pourrait être exécuté par le moteur comme une action R1 (sans approbation) si l'outil est mal classé. **C'est la correction la plus directement liée à la sécurité** (AGT-005).

---

## 4. Ce qui manque côté moteur pour charger le package

| Brique | État | Effort estimé |
|---|---|---|
| Table `agents` (tenant-scoped, versionnée, statut par capacité) | absente | 1 migration + modèle + tests |
| Table `agent_capabilities` (outil → statut → niveau d'approbation) | absente | même migration |
| Schéma Pydantic de `config.yaml` + validateur | absent | 1 module dédié |
| Chargeur de registre (refus si invalide) | absent | 1 service |
| Répartiteur plan → contrats de tâche | absent | extension de l'orchestrateur |
| Journal d'exécution par agent (`agent_runs`) | absent | 1 table + hooks |
| Messages inter-agents normalisés | absents | 1 contrat + 1 table |

Tant que ces briques n'existent pas, **aucun agent du package ne peut être activé**, quel que soit le contenu des fichiers.

---

## 5. Risques d'intégration spécifiques à KWES

**5.1 Le worker contourne la RLS.** L'API applique la RLS (`kwes_app` + claims posés par connexion) ; le worker utilise le rôle propriétaire (`DB_RLS_BYPASS=true`) parce qu'il traite toutes les missions. Si les agents s'exécutent dans le worker — ce qui est l'implémentation naturelle —, l'isolation multi-tenant ne repose plus sur PostgreSQL mais sur le code. Une erreur de filtre donne un accès croisé. C'est l'anomalie AGT-019, et c'est le point le plus risqué de l'intégration.

**5.2 Le vocabulaire divise.** Le package parle d'« agents », le moteur de « skills ». Sans table de correspondance, on risque d'implémenter un second système d'exécution à côté de l'existant, avec deux politiques et deux journaux.

**5.3 Le coût n'est pas modélisé.** 16 agents × 4 en parallèle × 180 s de délai, sans budget : les plafonds actuels (budget vocal 3 €/jour, quotas LLM) ne couvrent pas ce mode. La configuration doit porter un budget avant activation (AGT-009).

**5.4 La voix n'est pas couverte par les agents.** Le package décrit Core comme interface vocale, mais les 16 spécialistes n'ont aucune contrainte de voix (langue, une seule voix, barge-in). En l'état, un spécialiste pourrait produire une réponse non conforme à la politique vocale déjà en place.

---

## 6. Ce qui est déjà compatible

- **Modèles** : strictement conformes, aucun fournisseur de secours.
- **Refus par défaut** : identique dans les deux systèmes (`default_decision: deny` ↔ politique R3/R4 refusée).
- **Approbations** : le moteur possède déjà la mécanique (table `approvals`, hash de payload, expiration), il manque seulement le vocabulaire A0–A4.
- **Missions** : `tasks`/`task_steps`/`executions` correspondent au modèle de Core (`mission`, `étape`, `exécution`) ; `checkpoint_interval_steps: 3` est réalisable.
- **Preuves** : `evidence` et `audit_logs` existent, ce qui rend le contrat `agent-result` (champs `evidence`, `limitations`) implémentable sans nouvelle table.
- **Multi-tenant** : `tenant_id` présent sur 21 tables et politiques RLS actives, à condition de traiter le point 5.1.

---

## 7. Verdict de compatibilité

**Incompatible en l'état, compatible après trois briques.**

Le package n'est pas faux : il décrit une architecture cohérente avec KWES (mêmes modèles, même source de vérité, même refus par défaut, même exigence de preuves). Mais il n'existe aujourd'hui **aucun composant capable de le lire**, et **41 de ses 54 outils n'ont pas d'implémentation**.

Ordre minimal pour rendre l'intégration possible :

1. registre + chargeur + schéma de validation ;
2. table des capacités avec statut réel et matrice d'approbation ;
3. répartiteur de tâches et journal par agent ;
4. exécution respectant l'isolation tenant ;
5. activation progressive, agent par agent, après tests bout en bout.

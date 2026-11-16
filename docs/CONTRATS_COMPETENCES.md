# Contrats des futures compétences natives Kwes

**Statut : document de conception. Aucune de ces compétences n'existe dans le registre.**
P0 n'ajoute aucun skill fictif : `backend/app/skills/` contient toujours exactement
`web_research`, `browser_readonly`, `business_planning`, `remember`, `document_write`.

Chaque compétence future devra respecter le format réel du registre, vérifié à l'exécution :

```
backend/app/skills/<nom>/
├── manifest.yaml          # nom, version, risque, permissions, timeout, artefact
├── schemas/input.json     # JSON Schema 2020-12, additionalProperties: false
├── schemas/output.json    # JSON Schema 2020-12
└── skill.py               # async def run(payload, ctx) -> SkillResult
```

Règles communes (déjà appliquées par le registre et le Policy Engine) :

1. **Manifeste** : `name`, `version`, `description`, `risk_level` (`R0`–`R4`),
   `permissions` (sous-ensemble de la liste blanche codée en dur), `timeout_seconds`.
   Un manifeste ne peut pas élargir ses droits : le registre refuse toute permission hors liste.
2. **Schémas stricts** : entrée et sortie validées avant et après exécution ; une sortie non
   conforme est une erreur, pas un succès partiel.
3. **Politique** : chaque appel passe par `PolicyEngine.evaluate_skill_call` (dans l'API comme
   dans le worker). Aucune permission n'est accordée par le modèle ni par le worker.
4. **Journalisation** : `audit_logs` (acteur, action, décision, ressource) + journal applicatif.
   Jamais de secret, jamais de contenu utilisateur intégral.
5. **Erreurs** : codes explicites (`SKILL_VALIDATION`, `SKILL_TIMEOUT`, `FORBIDDEN`, `UPSTREAM`),
   message utilisateur compréhensible, aucune donnée inventée en cas d'échec.
6. **Tests** : un test nominal, un test de refus (permission/politique), un test d'erreur amont,
   un test de schéma. Sans ces quatre tests, la compétence n'entre pas dans `CHAT_TOOL_NAMES`.
7. **Outils conversationnels** : ajout à `CHAT_TOOL_NAMES` uniquement pour les actions `R0`/`R1`
   sans effet externe. Tout ce qui envoie, publie ou partage reste en mission + approbation.

---

## 1. `research` (extension de `web_research`) — P1

| Champ | Valeur cible |
|---|---|
| Risque | `R0` (lecture) |
| Permissions | `network.read`, `local.read` |
| Entrée | `query` (3–500), `depth` (`quick|standard|deep`), `scope`, `freshness_days?`, `sources_max` (1–10) |
| Sortie | `answer_markdown`, `sources[]` (`url`, `title`, `excerpt`, `read_at`, `evidence_id`), `coverage` |
| Politique | `ALLOW` en lecture ; refus si l'URL résout vers une IP privée, un port non web ou un hôte interne |
| Tests | sources réelles citées ; 0 source → échec explicite ; PDF lu ; page JS rendue |
| Notes | coexistence de deux fournisseurs (SearXNG + repli DDG/Wikipédia), cache Redis 24 h, compteur de requêtes |

## 2. `memory` (extension de `remember`) — P2

| Champ | Valeur cible |
|---|---|
| Risque | `R1` |
| Permissions | `local.write`, `network.read` (embeddings) |
| Entrée | `action` (`remember|forget|search`), `content?`, `query?`, `category`, `sensitivity` |
| Sortie | `memories[]` (`id`, `content`, `score`, `provenance`, `expires_at`) |
| Politique | isolation stricte par `user_id` ; `sensitive` jamais réinjecté sans demande explicite |
| Tests | recherche sémantique > lexicale ; fuite inter-utilisateurs impossible ; expiration appliquée |
| Notes | pgvector déjà présent ; interface d'embedding remplaçable ; conservation du retrieval lexical |

## 3. `files` — P3

| Champ | Valeur cible |
|---|---|
| Risque | `R1` (import) / `R2` (partage) |
| Permissions | `local.write`, `local.read`, `storage.write` |
| Entrée | `action` (`ingest|extract|search`), `file_id?`, `path?`, `mime?` |
| Sortie | `file_id`, `mime`, `pages`, `extract_markdown`, `warnings[]` |
| Politique | quarantaine avant analyse ; refus si MIME déclaré ≠ MIME réel ; taille max |
| Tests | 8 formats ; fichier piégé refusé ; isolation ; extraction PDF/OCR |
| Notes | stockage Supabase Storage, OCR Tesseract local, parsing isolé, antivirus |

## 4. `automations` — P5

| Champ | Valeur cible |
|---|---|
| Risque | `R2` (déclenche une action) |
| Permissions | `local.write`, `scheduler.write` |
| Entrée | `action` (`create|pause|resume|delete`), `trigger` (`cron|event|threshold`), `task_template` |
| Sortie | `workflow_id`, `next_run_at`, `status` |
| Politique | toute automatisation est créée par un humain ; chaque exécution repasse les politiques |
| Tests | survie au redémarrage ; pas de double exécution ; DLQ ; pause immédiate |
| Notes | scheduler durable, table `workflows`/`workflow_runs`, DLQ, historique |

## 5. `agenda` — P4

| Champ | Valeur cible |
|---|---|
| Risque | `R1` (lecture) / `R2` (création, invitation) |
| Permissions | `network.read`, `calendar.write` |
| Entrée | `action` (`list|find_slot|create|cancel`), `time_min`, `time_max`, `timezone` (IANA), `attendees?` |
| Sortie | `events[]`, `conflicts[]`, `created_event_id?` |
| Politique | toute création avec invités = `R2` + approbation ; fuseau obligatoire |
| Tests | conflit détecté ; fuseau exact ; annulation approuvée ; rappel persistant |
| Notes | Google Calendar (hors P0), OAuth, rappels via scheduler |

## 6. `email` — P6

| Champ | Valeur cible |
|---|---|
| Risque | `R0` (lecture) / `R1` (brouillon) / `R2` (envoi) |
| Permissions | `network.read`, `mail.read`, `mail.draft`, `mail.send` |
| Entrée | `action` (`search|read|draft|send`), `query?`, `thread_id?`, `to?`, `subject?`, `body?` |
| Sortie | `messages[]`, `draft_id?`, `sent_id?` |
| Politique | `send` interdit sans approbation liée au hachage exact du message ; scopes minimaux |
| Tests | brouillon ≠ envoi ; modification du corps invalide l'approbation ; révocation du jeton |
| Notes | Gmail, OAuth, aucun envoi automatique, aucune connexion pendant P0 |

---

## Ce que P0 garantit à ces compétences

- Un cycle de vie clair : l'API crée l'intention, le worker exécute, la base garde l'état.
- Un verrou par tâche : deux workers ne peuvent pas exécuter la même étape en parallèle.
- Une reprise : une tâche interrompue est reprise, une tâche abandonnée est balayée toutes les 30 s.
- Un audit : chaque décision et chaque appel sont journalisés, dans l'API comme dans le worker.
- Un rollback : la désactivation du service worker suffit à revenir au mode historique.

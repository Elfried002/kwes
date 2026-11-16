# KWES — Preuves de tests, RLS et Policy Engine

Généré le 16/11/2026 à partir de l'environnement réel (PostgreSQL 16 dans Docker, Python 3.14.7).
Toute ligne ci-dessous correspond à une commande exécutée et à sa sortie, pas à une intention.

---

## 1. Suite de tests backend

Commande : `cd backend && . .venv/bin/activate && python -m pytest -q`

```
134 passed, 1 warning in 36.51s
```

| Fichier | Tests | Ce qui est couvert |
|---|---|---|
| `test_skills.py` | 27 | schémas d'entrée/sortie, timeout, contenu malveillant, allowlist, extraction |
| `test_policy.py` | 14 | matrice R0–R4 (voir §3) |
| `test_infra.py` | 12 | schéma des 15 tables, adaptateurs MOCK, worker, repli voix |
| `test_chat_stream.py` | 12 | SSE : auth requise, événements `delta`/`done`/`error`, LLM mocké |
| `test_auth.py` | 11 | absence de jeton, jeton invalide/expiré/mauvais secret, profil auto-créé |
| `test_chat.py` | 10 | réponse directe, création de mission, persistance, erreurs fournisseur |
| `test_tasks.py` | 9 | création, progression, annulation, pause/reprise, états |
| `test_planner.py` | 8 | plan JSON validé, refus des plans invalides, mapping compétences |
| `test_devices.py` | 6 | connecteurs : jeton, rotation, révocation, isolation inter-utilisateurs |
| `test_ws.py` | 6 | authentification WebSocket, enveloppe d'événements, origin |
| `test_approvals.py` | 6 | approbation liée à un hash, expiration, refus |
| `test_isolation.py` | 5 | un utilisateur ne lit ni ne modifie les données d'un autre |
| `test_health.py` | 5 | `/health` et `/api/v1/health`, dépendances, absence de fuite |
| `test_conversations.py` | 3 | création, liste, suppression avec données dérivées |

Avertissement unique : `StarletteDeprecationWarning` (TestClient + httpx2). Sans effet fonctionnel.

---

## 2. Row Level Security — 39 politiques actives

Requête exécutée sur la base réelle :

```sql
select tablename, policyname, cmd, roles from pg_policies where schemaname='public';
```

| Table | Politiques | Commandes couvertes |
|---|---|---|
| `conversations` | 4 | SELECT, INSERT, UPDATE, DELETE |
| `device_connectors` | 4 | SELECT, INSERT, UPDATE, DELETE |
| `memories` | 4 | SELECT, INSERT, UPDATE, DELETE |
| `messages` | 4 | SELECT, INSERT, UPDATE, DELETE |
| `task_steps` | 4 | SELECT, INSERT, UPDATE, DELETE |
| `tasks` | 4 | SELECT, INSERT, UPDATE, DELETE |
| `notifications` | 3 | SELECT, INSERT, UPDATE |
| `profiles` | 3 | SELECT, INSERT, UPDATE |
| `device_commands` | 2 | SELECT, INSERT |
| `integrations` | 2 | SELECT, DELETE |
| `approvals` | 1 | SELECT |
| `audit_logs` | 1 | SELECT (écriture réservée au serveur) |
| `executions` | 1 | SELECT |
| `skill_versions` | 1 | SELECT (référentiel, lecture seule) |
| `skills` | 1 | SELECT (référentiel, lecture seule) |

**Condition type** : `user_id = (select auth.uid())`, avec `WITH CHECK` identique sur INSERT/UPDATE.
**Aucune politique `always true`** hors les deux référentiels `skills`/`skill_versions` (lecture seule assumée, contenu non sensible).
**Rôles** : `authenticated` uniquement ; `anon` n'a aucune politique, donc aucun accès.

Tests RLS fonctionnels exécutés sur PostgreSQL réel (`supabase/tests/rls_test.sql`, 13 assertions) : un second utilisateur voit 0 ligne privée, les insertions au nom d'autrui sont refusées (`insufficient_privilege`), les référentiels restent lisibles par tous les authentifiés.

---

## 3. Policy Engine — 14 tests, résultat intégral

| Test | Ce qu'il prouve | Résultat |
|---|---|---|
| `test_r0_read_is_allowed` | lecture autorisée sans validation | PASSED |
| `test_r1_local_preparation_is_allowed` | préparation locale autorisée | PASSED |
| `test_r2_external_publish_requires_approval` | action externe → validation obligatoire | PASSED |
| `test_llm_cannot_lower_risk_with_declared_r0` | **le LLM ne peut pas abaisser son propre risque** | PASSED |
| `test_declared_higher_risk_is_honoured` | un risque déclaré plus élevé est respecté | PASSED |
| `test_r3_financial_action_is_denied` | paiement refusé par défaut | PASSED |
| `test_r4_prompt_injection_is_denied` | injection de prompt = refus | PASSED |
| `test_unknown_skill_is_denied_by_default` | deny-by-default sur compétence inconnue | PASSED |
| `test_unknown_action_is_denied_by_default` | deny-by-default sur action inconnue | PASSED |
| `test_domain_outside_allowlist_is_denied` | domaine hors allowlist refusé | PASSED |
| `test_r2_allowed_with_valid_approval` | approbation valide débloque l'action | PASSED |
| `test_expired_approval_is_not_usable` | approbation expirée inutilisable | PASSED |
| `test_approval_hash_mismatch_is_not_usable` | **approbation liée au contenu** : modifier la charge invalide l'accord | PASSED |
| `test_action_registry_payment_denied` | registre d'actions : paiement refusé | PASSED |

**Conséquence** : le modèle ne peut ni s'auto-autoriser, ni modifier ses permissions, ni réutiliser une approbation pour une autre action.

---

## 4. Base de données et migrations

- 7 migrations appliquées en local **et** sur le projet Supabase de production (`db push --remote --yes`).
- 15 tables, 39 politiques RLS, 3 compétences seedées, index `pgvector` (HNSW) sur `memories.embedding`.
- Migrations idempotentes : 0004 rendue conditionnelle après un échec réel sur base neuve.

---

## 5. Ce qui n'est pas prouvé

| Élément | Statut | Raison |
|---|---|---|
| Tests RLS exécutés sur Supabase distant | `blocked` | nécessite une connexion SQL distante (mot de passe base non fourni) ; validés sur PostgreSQL 16 local |
| Reconnaissance vocale avec un vrai microphone | `blocked` | aucun appareil physique accessible depuis le serveur ; à valider sur ton téléphone |
| Google OAuth | `blocked` | fournisseur non configuré côté Supabase (Client ID/Secret manquants) |
| Compagnon Android / agent desktop | `planned` | socle backend livré, clients non développés |

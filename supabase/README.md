# Kwes — migrations Supabase

Schéma de données, Row Level Security et seed des skills Alpha.
Source de vérité des colonnes : [`docs/06-data/DATA_MODEL.md`](../docs/06-data/DATA_MODEL.md)
et [`CONTRACTS.md`](../CONTRACTS.md).

## 1. Contenu

```
supabase/
├── migrations/
│   ├── 0001_init.sql         13 tables, contraintes, index, pgvector, triggers
│   ├── 0002_rls.sql          ENABLE RLS + 33 policies + privilèges
│   └── 0003_seed_skills.sql  3 skills Alpha en version active
├── local/
│   └── 0000_local_auth_shim.sql   ⚠️ local/CI seulement (émule auth.uid())
├── scripts/
│   ├── checks.sql            requêtes de contrôle post-migration
│   ├── verify_local.sh       application + contrôles sur base jetable Docker
│   └── down_all.sql          rollback destructif (dev uniquement)
└── tests/
    └── rls_test.sql          test fonctionnel d'isolation entre utilisateurs
```

### Les 13 tables

| Table | Propriétaire | Écriture client | Notes |
|---|---|---|---|
| `profiles` | `auth.users.id` | SELECT, INSERT, UPDATE | pas de DELETE (cascade via `auth.users`) |
| `conversations` | `user_id` | CRUD | `status` ∈ active/archived/deleted |
| `messages` | `user_id` + conversation | CRUD | double contrôle d'appartenance |
| `tasks` | `user_id` | CRUD | statuts du contrat (8 valeurs) |
| `task_steps` | via `tasks` | CRUD | pas de `user_id`, policy par jointure |
| `executions` | via `tasks` | SELECT seul | écrit par le worker (`service_role`) |
| `skills` | référentiel | SELECT seul | lecture authentifiée |
| `skill_versions` | référentiel | SELECT seul | 1 seule version `active` par skill (index partiel) |
| `memories` | `user_id` | CRUD | `embedding vector(1536)` + index HNSW |
| `approvals` | `user_id` | SELECT seul | décision via l'API (payload_hash) |
| `integrations` | `user_id` | SELECT, DELETE | `secret_reference` jamais le secret |
| `audit_logs` | `user_id` | SELECT seul | append-only côté serveur |
| `notifications` | `user_id` | SELECT, UPDATE, DELETE | INSERT réservé au backend |

## 2. Appliquer sur Supabase (production)

### Option A — Supabase CLI (recommandé)

```bash
supabase login
supabase link --project-ref <project-ref>
supabase db push --dry-run        # diff des migrations à appliquer
supabase db push                  # applique 0001, 0002, 0003 dans l'ordre
```

`supabase db push` s'appuie sur l'historique `supabase_migrations.schema_migrations` :
les fichiers déjà appliqués sont ignorés.

### Option B — psql / pooler

```bash
export DATABASE_URL='postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require'

for f in supabase/migrations/*.sql; do
  echo "== $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

Chaque fichier est **transactionnel** (`begin` / `commit`) : en cas d'erreur,
rien n'est laissé à moitié appliqué. `ON_ERROR_STOP=1` est indispensable —
sans lui, `psql` continue et vous obtenez un schéma partiel.

> Ne **jamais** appliquer `supabase/local/0000_local_auth_shim.sql` sur Supabase :
> `auth.users`, `auth.uid()` et les rôles existent déjà.

## 3. Vérifier après migration

```bash
psql "$DATABASE_URL" -f supabase/scripts/checks.sql
```

Contrôles clés et résultat attendu :

```sql
-- 1. 13 tables applicatives, toutes avec RLS
select c.relname, c.relrowsecurity,
       (select count(*) from pg_policy p where p.polrelid = c.oid) as policies
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r'
 order by 1;
-- attendu : 13 lignes, relrowsecurity = true partout, 33 policies au total

-- 2. Aucune table privée sans RLS (doit renvoyer 0 ligne)
select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity = false;

-- 3. Aucune policy « always-true » hors référentiel (doit renvoyer 0 ligne)
select tablename, policyname from pg_policies
 where schemaname = 'public' and qual = 'true'
   and tablename not in ('skills', 'skill_versions');

-- 4. pgvector
select format_type(atttypid, atttypmod) from pg_attribute
 where attrelid = 'public.memories'::regclass and attname = 'embedding';
-- attendu : vector(1536)

-- 5. Seed
select s.name, v.version, v.status from public.skills s
  join public.skill_versions v on v.skill_id = s.id and v.version = s.current_version;
-- attendu : web_research, business_planning, browser_readonly — 1.0.0 / active

-- 6. Isolation réelle (pas seulement « RLS activée »)
--    -> psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/rls_test.sql
```

## 4. Vérification locale complète (rejouée en CI)

Testé sur PostgreSQL 16 + pgvector 0.8.7, image `pgvector/pgvector:pg16` :

```bash
bash supabase/scripts/verify_local.sh                    # Docker direct
DOCKER="sudo docker" bash supabase/scripts/verify_local.sh
```

Le script démarre un conteneur jetable, applique le shim + les 3 migrations,
**les réapplique** (preuve d'idempotence), lance `checks.sql` puis
`tests/rls_test.sql`, et supprime le conteneur.

Sortie réelle (2026-11-16) :

```
>> 0001_init.sql
NOTICE:  profiles_id_fkey -> auth.users : ajoutée
NOTICE:  trigger on_auth_user_created : créé sur auth.users
>> idempotence : réapplication de 0001/0002/0003
   OK — réexécution sans erreur
=== 1. Vue d'ensemble des tables (RLS activée ?) ===
     table      | rls | policies
----------------+-----+----------
 approvals      | t   |        1
 audit_logs     | t   |        1
 conversations  | t   |        4
 executions     | t   |        1
 integrations   | t   |        2
 memories       | t   |        4
 messages       | t   |        4
 notifications  | t   |        3
 profiles       | t   |        3
 skill_versions | t   |        1
 skills         | t   |        1
 task_steps     | t   |        4
 tasks          | t   |        4
(13 rows)
=== 3. Tables dont la RLS serait désactivée ===
(0 rows)
=== 5. Policies suspectes (always-true) ===
(0 rows)
=== 7. pgvector ===
 pgcrypto | 1.3
 vector   | 0.8.7
 embedding | vector(1536)
 idx_memories_embedding | CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WHERE (embedding IS NOT NULL)
=== 8. Seed skills ===
 browser_readonly  | 1.0.0 | t | 1.0.0 | active
 business_planning | 1.0.0 | t | 1.0.0 | active
 web_research      | 1.0.0 | t | 1.0.0 | active
NOTICE:  OK  handle_new_user : 2 profils auto-créés
NOTICE:  OK  Alice voit exactement ses 6 lignes (conv, msg, task, step, memory, profil)
NOTICE:  OK  Bob ne voit aucune ligne privée d'Alice ; les 3 skills restent lisibles
NOTICE:  OK  insert memories(user_id=Alice) par Bob refusé par la RLS
NOTICE:  OK  insert conversations(user_id=Alice) par Bob refusé par la RLS
NOTICE:  OK  task rattachée à la conversation d'Alice refusée
NOTICE:  OK  insert executions refusé (table en lecture seule côté client)
NOTICE:  OK  insert audit_logs refusé (journal serveur uniquement)
NOTICE:  OK  insert skills refusé (référentiel en lecture seule)
NOTICE:  OK  update/delete inter-utilisateur : 0 ligne affectée
NOTICE:  OK  anon refusé sur conversations (permission denied)
NOTICE:  OK  anon refusé sur memories (permission denied)
NOTICE:  OK  sans claim sub : 0 ligne visible (auth.uid() NULL)
=== RLS : toutes les assertions sont passées ===
```

## 5. Modèle de sécurité RLS

| Règle | Mise en œuvre |
|---|---|
| `user_id = auth.uid()` | toutes les tables privées, en `USING` **et** en `WITH CHECK` |
| `auth.uid()` évalué une fois | écrit `(select auth.uid())` (init-plan, pas de re-évaluation par ligne) |
| rôles | policies `to authenticated` uniquement ; `anon` n'a **aucun** privilège |
| tables de référence | `skills` / `skill_versions` : `SELECT` seul |
| tables serveur | `executions`, `audit_logs`, `approvals`, `integrations` : écriture impossible côté client |
| rattachement indirect | `task_steps` / `executions` via `EXISTS (... tasks.user_id = auth.uid())` |
| backend | écrit avec `service_role` (bypass RLS), jamais avec la clé anon |
| `FORCE ROW LEVEL SECURITY` | **non activé** : il casserait le seed et les restaurations exécutés par le rôle propriétaire, sans apport de sécurité face à `service_role` (qui bypass de toute façon) |

`using (true)` n'apparaît que sur `skills` et `skill_versions`, avec
`to authenticated` : c'est un référentiel partagé, pas une donnée privée.

## 6. Rollback

Trois niveaux, du moins au plus destructif.

**a. Migration suivante (recommandé).** Les migrations sont additives : une
correction = un `0004_*.sql`. Ne jamais éditer un fichier déjà appliqué (les
environnements divergent alors silencieusement).

```sql
-- supabase/migrations/0004_fix_quelque_chose.sql
begin;
alter table public.tasks add column if not exists ...;
commit;
```

**b. Retour arrière applicatif.** Redéployer l'image N-1 (`KWES_VERSION`) :
le schéma reste compatible car les migrations sont additives pendant l'Alpha.

**c. Restauration base.** Depuis un dump ou le PITR Supabase :

```bash
# dump local
pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" backup.dump
# Supabase : Dashboard > Database > Backups > Restore (PITR selon l'offre)
```

**d. Suppression totale (dev uniquement).**

```bash
psql "$DATABASE_URL" \
  -c "select set_config('kwes.confirm_drop','yes',false);" \
  -f supabase/scripts/down_all.sql
```

Avant toute migration destructive en production : dump vérifié
(`infra/scripts/backup.sh`) et test de restauration sur une base jetable.

## 7. Conventions pour les prochaines migrations

- nommage `NNNN_description.sql`, une intention par fichier ;
- `begin` / `commit` explicites, `IF NOT EXISTS` sur tout objet ;
- aucune donnée de production modifiée hors migration dédiée et annoncée ;
- policies nommées `<table>_<cmd>_<portée>` et toujours `to authenticated` ;
- `drop policy if exists` avant `create policy` (idempotence) ;
- toute nouvelle table privée : `user_id`, `ENABLE ROW LEVEL SECURITY`, 4 policies ;
- vérifier avec `checks.sql` + `tests/rls_test.sql` avant de pousser.

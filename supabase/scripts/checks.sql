-- =============================================================================
-- Kwes — supabase/scripts/checks.sql
-- Requêtes de contrôle post-migration (lecture seule, ne modifie rien).
-- Utilisées par supabase/scripts/verify_local.sh et par le job CI `migrations`.
--
-- Sortie attendue : 13 tables avec rls=true, des policies uniquement sur les
-- 13 tables, 3 skills actifs, l'extension vector et l'index HNSW présents.
-- =============================================================================

\echo '=== 1. Vue d''ensemble des tables (RLS activée ?) ==='
select c.relname                                   as table,
       c.relrowsecurity                            as rls,
       c.relforcerowsecurity                       as rls_force,
       (select count(*) from pg_policy p where p.polrelid = c.oid) as policies
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public'
   and c.relkind = 'r'
 order by c.relname;

\echo ''
\echo '=== 2. Nombre de tables applicatives attendues (13) ==='
select count(*) as tables_applicatives
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public'
   and c.relkind = 'r'
   and c.relname in (
       'profiles','conversations','messages','tasks','task_steps','executions',
       'skills','skill_versions','memories','approvals','integrations',
       'audit_logs','notifications');

\echo ''
\echo '=== 3. Tables dont la RLS serait désactivée (doit renvoyer 0 ligne) ==='
select c.relname
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public'
   and c.relkind = 'r'
   and c.relname in (
       'profiles','conversations','messages','tasks','task_steps','executions',
       'skills','skill_versions','memories','approvals','integrations',
       'audit_logs','notifications')
   and c.relrowsecurity = false;

\echo ''
\echo '=== 4. Policies par table et par commande ==='
select tablename,
       cmd,
       count(*) as n,
       string_agg(policyname, ', ' order by policyname) as noms
  from pg_policies
 where schemaname = 'public'
 group by tablename, cmd
 order by tablename, cmd;

\echo ''
\echo '=== 5. Policies suspectes (always-true) hors tables de référence ==='
-- `using (true)` n'est toléré QUE sur skills / skill_versions (référentiel
-- public en lecture seule authentifiée).
select tablename, policyname, cmd, qual
  from pg_policies
 where schemaname = 'public'
   and qual = 'true'
   and tablename not in ('skills', 'skill_versions');

\echo ''
\echo '=== 6. Policies accordées à un rôle trop large (anon / public) ==='
select tablename, policyname, roles
  from pg_policies
 where schemaname = 'public'
   and (roles::text like '%anon%' or roles::text like '%public%');

\echo ''
\echo '=== 7. pgvector : extension, colonne, index ==='
select extname, extversion
  from pg_extension
 where extname in ('vector', 'pgcrypto');

select a.attname as colonne,
       format_type(a.atttypid, a.atttypmod) as type
  from pg_attribute a
  join pg_class c on c.oid = a.attrelid
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public'
   and c.relname = 'memories'
   and a.attname = 'embedding';

select indexname, indexdef
  from pg_indexes
 where schemaname = 'public'
   and tablename = 'memories'
   and indexdef ilike '%hnsw%';

\echo ''
\echo '=== 8. Seed skills (attendu : 3 skills, 3 versions actives) ==='
select s.name, s.current_version, s.enabled, v.version, v.status
  from public.skills s
  left join public.skill_versions v
         on v.skill_id = s.id and v.version = s.current_version
 order by s.name;

select count(*) filter (where status = 'active') as versions_actives,
       count(*)                                  as versions_total
  from public.skill_versions;

\echo ''
\echo '=== 9. Triggers updated_at ==='
select event_object_table as table, trigger_name
  from information_schema.triggers
 where trigger_schema = 'public'
   and trigger_name like 'trg_%_updated_at'
 order by 1;

\echo ''
\echo '=== 10. Contraintes de statut (tasks / task_steps) ==='
select conrelid::regclass as table, conname
  from pg_constraint
 where conname in ('tasks_status_check', 'task_steps_status_check')
 order by 1;

\echo ''
\echo '=== 11. Index clés (user_id / conversation_id / task_id / status) ==='
select tablename, indexname
  from pg_indexes
 where schemaname = 'public'
   and (indexname like 'idx\_%\_user\_id'  escape '\'
     or indexname like 'idx\_%conversation\_id%' escape '\'
     or indexname like 'idx\_%task\_id'    escape '\'
     or indexname like 'idx\_%status'      escape '\')
 order by 1, 2;

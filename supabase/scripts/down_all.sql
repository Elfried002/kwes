-- =============================================================================
-- Kwes — supabase/scripts/down_all.sql
--
-- ⚠️  DESTRUCTIF — supprime le schéma applicatif (13 tables + fonctions).
--     À n'utiliser qu'en développement ou pour un rollback explicitement
--     décidé. En production, préférer une restauration PITR / dump.
--
-- Le script refuse de s'exécuter sans confirmation explicite dans la session :
--   psql "$DATABASE_URL" \
--        -c "select set_config('kwes.confirm_drop','yes',false);" \
--        -f supabase/scripts/down_all.sql
-- =============================================================================

begin;

do $do$
begin
    if coalesce(current_setting('kwes.confirm_drop', true), '') <> 'yes' then
        raise exception
            'Refus : exécuter d''abord  select set_config(''kwes.confirm_drop'',''yes'',false);  dans la même session.';
    end if;
end
$do$;

-- Triggers et fonctions d'abord
do $do$
declare
    t text;
begin
    foreach t in array array[
        'profiles', 'conversations', 'tasks', 'task_steps', 'memories', 'integrations'
    ]
    loop
        execute format('drop trigger if exists trg_%1$s_updated_at on public.%1$s', t);
    end loop;
end
$do$;

do $do$
begin
    if exists (select 1 from pg_tables where schemaname = 'auth' and tablename = 'users') then
        execute 'drop trigger if exists on_auth_user_created on auth.users';
    end if;
end
$do$;

drop function if exists public.handle_new_user();
drop function if exists public.set_updated_at();

-- Tables dans l'ordre inverse des dépendances
drop table if exists public.audit_logs;
drop table if exists public.notifications;
drop table if exists public.approvals;
drop table if exists public.executions;
drop table if exists public.task_steps;
drop table if exists public.tasks;
drop table if exists public.messages;
drop table if exists public.conversations;
drop table if exists public.memories;
drop table if exists public.integrations;
drop table if exists public.skill_versions;
drop table if exists public.skills;
drop table if exists public.profiles;

-- Les extensions (vector, pgcrypto) sont laissées en place : elles peuvent
-- être partagées. Les supprimer manuellement si nécessaire :
--   drop extension if exists vector;

commit;

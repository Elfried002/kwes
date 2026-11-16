-- =============================================================================
-- Kwes — 0002_rls.sql
-- Row Level Security : isolation stricte des données par utilisateur.
--
-- Objectif : aucune ligne d'un utilisateur ne doit être lisible ou modifiable
-- par un autre, même avec un JWT valide et un client Supabase direct.
--
-- Principes :
--   * ENABLE (et FORCE hors propriétaire) ROW LEVEL SECURITY sur les 13 tables ;
--   * policies nommées, explicites, jamais `using (true)` sur une table privée ;
--   * `to authenticated` uniquement : `anon` n'a aucun accès ;
--   * `(select auth.uid())` pour éviter la réévaluation par ligne ;
--   * tables de référence (skills, skill_versions) : SELECT seul ;
--   * tables écrites par le serveur (executions, approvals, audit_logs,
--     integrations) : SELECT seul côté client, écriture réservée au backend ;
--   * `with check` sur toutes les écritures (empêche de forger un user_id).
--
-- Prérequis : auth.uid(), rôles anon/authenticated (fournis par Supabase ;
-- en local, appliquer supabase/local/0000_local_auth_shim.sql avant).
-- =============================================================================

begin;

-- Garde-fou : échouer tôt avec un message actionnable plutôt qu'en plein milieu.
do $do$
begin
    if not exists (
        select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'auth' and p.proname = 'uid'
    ) then
        raise exception
            'auth.uid() introuvable : appliquer supabase/local/0000_local_auth_shim.sql (Supabase le fournit nativement).';
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated')
       or not exists (select 1 from pg_roles where rolname = 'anon') then
        raise exception
            'rôles anon/authenticated absents : appliquer supabase/local/0000_local_auth_shim.sql (Supabase les fournit nativement).';
    end if;
end
$do$;

-- -----------------------------------------------------------------------------
-- 1. Activation de RLS
-- -----------------------------------------------------------------------------
do $do$
declare
    t text;
begin
    foreach t in array array[
        'profiles', 'conversations', 'messages', 'tasks', 'task_steps', 'executions',
        'skills', 'skill_versions', 'memories', 'approvals', 'integrations',
        'audit_logs', 'notifications'
    ]
    loop
        execute format('alter table public.%I enable row level security', t);
        -- FORCE n'est volontairement PAS activé : les migrations et les
        -- sauvegardes s'exécutent avec le rôle propriétaire (postgres /
        -- supabase_admin), et FORCE casserait le seed 0003 ainsi que les
        -- restaurations. L'isolation des utilisateurs est portée par les
        -- policies `to authenticated` ci-dessous ; le backend écrit avec
        -- service_role, qui bypass la RLS par conception.
    end loop;
end
$do$;

-- -----------------------------------------------------------------------------
-- 2. Privilèges de table
--    Supabase accorde par défaut ALL à anon/authenticated sur public ; on
--    resserre explicitement pour que le comportement soit identique en local
--    et en production.
-- -----------------------------------------------------------------------------
do $do$
declare
    t text;
begin
    foreach t in array array[
        'profiles', 'conversations', 'messages', 'tasks', 'task_steps', 'executions',
        'skills', 'skill_versions', 'memories', 'approvals', 'integrations',
        'audit_logs', 'notifications'
    ]
    loop
        execute format('revoke all on public.%I from anon', t);
    end loop;

    -- CRUD complet pour l'utilisateur sur ses propres contenus
    foreach t in array array['profiles', 'conversations', 'messages', 'tasks', 'task_steps', 'memories']
    loop
        execute format('grant select, insert, update, delete on public.%I to authenticated', t);
    end loop;

    -- Lecture seule côté client (écriture serveur / service_role)
    foreach t in array array['executions', 'skills', 'skill_versions', 'approvals', 'integrations', 'audit_logs']
    loop
        execute format('grant select on public.%I to authenticated', t);
    end loop;

    -- Notifications : l'utilisateur peut lire, marquer comme lu, supprimer
    execute 'grant select, update, delete on public.notifications to authenticated';
end
$do$;

-- -----------------------------------------------------------------------------
-- 3. profiles
-- -----------------------------------------------------------------------------
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select to authenticated
    using (id = (select auth.uid()));

drop policy if exists profiles_insert_own on public.profiles;
create policy profiles_insert_own on public.profiles
    for insert to authenticated
    with check (id = (select auth.uid()));

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
    for update to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));
-- Pas de policy DELETE : la suppression de compte passe par auth.users
-- (cascade profiles_id_fkey), jamais par un DELETE direct côté client.

-- -----------------------------------------------------------------------------
-- 4. conversations
-- -----------------------------------------------------------------------------
drop policy if exists conversations_select_own on public.conversations;
create policy conversations_select_own on public.conversations
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists conversations_insert_own on public.conversations;
create policy conversations_insert_own on public.conversations
    for insert to authenticated
    with check (user_id = (select auth.uid()));

drop policy if exists conversations_update_own on public.conversations;
create policy conversations_update_own on public.conversations
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists conversations_delete_own on public.conversations;
create policy conversations_delete_own on public.conversations
    for delete to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 5. messages
--    Double contrôle : user_id ET appartenance de la conversation.
-- -----------------------------------------------------------------------------
drop policy if exists messages_select_own on public.messages;
create policy messages_select_own on public.messages
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists messages_insert_own on public.messages;
create policy messages_insert_own on public.messages
    for insert to authenticated
    with check (
        user_id = (select auth.uid())
        and exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
              and c.user_id = (select auth.uid())
        )
    );

drop policy if exists messages_update_own on public.messages;
create policy messages_update_own on public.messages
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists messages_delete_own on public.messages;
create policy messages_delete_own on public.messages
    for delete to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 6. tasks
-- -----------------------------------------------------------------------------
drop policy if exists tasks_select_own on public.tasks;
create policy tasks_select_own on public.tasks
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists tasks_insert_own on public.tasks;
create policy tasks_insert_own on public.tasks
    for insert to authenticated
    with check (
        user_id = (select auth.uid())
        and (
            conversation_id is null
            or exists (
                select 1 from public.conversations c
                where c.id = tasks.conversation_id
                  and c.user_id = (select auth.uid())
            )
        )
    );

drop policy if exists tasks_update_own on public.tasks;
create policy tasks_update_own on public.tasks
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists tasks_delete_own on public.tasks;
create policy tasks_delete_own on public.tasks
    for delete to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 7. task_steps (pas de user_id : rattachement via tasks)
-- -----------------------------------------------------------------------------
drop policy if exists task_steps_select_own on public.task_steps;
create policy task_steps_select_own on public.task_steps
    for select to authenticated
    using (
        exists (
            select 1 from public.tasks t
            where t.id = task_steps.task_id
              and t.user_id = (select auth.uid())
        )
    );

drop policy if exists task_steps_insert_own on public.task_steps;
create policy task_steps_insert_own on public.task_steps
    for insert to authenticated
    with check (
        exists (
            select 1 from public.tasks t
            where t.id = task_steps.task_id
              and t.user_id = (select auth.uid())
        )
    );

drop policy if exists task_steps_update_own on public.task_steps;
create policy task_steps_update_own on public.task_steps
    for update to authenticated
    using (
        exists (
            select 1 from public.tasks t
            where t.id = task_steps.task_id
              and t.user_id = (select auth.uid())
        )
    )
    with check (
        exists (
            select 1 from public.tasks t
            where t.id = task_steps.task_id
              and t.user_id = (select auth.uid())
        )
    );

drop policy if exists task_steps_delete_own on public.task_steps;
create policy task_steps_delete_own on public.task_steps
    for delete to authenticated
    using (
        exists (
            select 1 from public.tasks t
            where t.id = task_steps.task_id
              and t.user_id = (select auth.uid())
        )
    );

-- -----------------------------------------------------------------------------
-- 8. executions — lecture seule (écrites par le worker, service_role)
-- -----------------------------------------------------------------------------
drop policy if exists executions_select_own on public.executions;
create policy executions_select_own on public.executions
    for select to authenticated
    using (
        exists (
            select 1 from public.tasks t
            where t.id = executions.task_id
              and t.user_id = (select auth.uid())
        )
    );

-- -----------------------------------------------------------------------------
-- 9. skills / 10. skill_versions — référentiel public authentifié, lecture seule
--    Aucune policy d'écriture : RLS activé + absence de policy = refus.
-- -----------------------------------------------------------------------------
drop policy if exists skills_select_authenticated on public.skills;
create policy skills_select_authenticated on public.skills
    for select to authenticated
    using (true);

drop policy if exists skill_versions_select_authenticated on public.skill_versions;
create policy skill_versions_select_authenticated on public.skill_versions
    for select to authenticated
    using (true);

-- -----------------------------------------------------------------------------
-- 11. memories
-- -----------------------------------------------------------------------------
drop policy if exists memories_select_own on public.memories;
create policy memories_select_own on public.memories
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists memories_insert_own on public.memories;
create policy memories_insert_own on public.memories
    for insert to authenticated
    with check (user_id = (select auth.uid()));

drop policy if exists memories_update_own on public.memories;
create policy memories_update_own on public.memories
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists memories_delete_own on public.memories;
create policy memories_delete_own on public.memories
    for delete to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 12. approvals — lecture seule : la décision passe par l'API
--     (POST /api/v1/approvals/{id}/approve) qui vérifie payload_hash + policy.
-- -----------------------------------------------------------------------------
drop policy if exists approvals_select_own on public.approvals;
create policy approvals_select_own on public.approvals
    for select to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 13. integrations — lecture + déconnexion ; jamais de secret côté client
-- -----------------------------------------------------------------------------
drop policy if exists integrations_select_own on public.integrations;
create policy integrations_select_own on public.integrations
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists integrations_delete_own on public.integrations;
create policy integrations_delete_own on public.integrations
    for delete to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 14. audit_logs — lecture seule de ses propres traces, aucun effacement
-- -----------------------------------------------------------------------------
drop policy if exists audit_logs_select_own on public.audit_logs;
create policy audit_logs_select_own on public.audit_logs
    for select to authenticated
    using (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- 15. notifications
-- -----------------------------------------------------------------------------
drop policy if exists notifications_select_own on public.notifications;
create policy notifications_select_own on public.notifications
    for select to authenticated
    using (user_id = (select auth.uid()));

drop policy if exists notifications_update_own on public.notifications;
create policy notifications_update_own on public.notifications
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists notifications_delete_own on public.notifications;
create policy notifications_delete_own on public.notifications
    for delete to authenticated
    using (user_id = (select auth.uid()));

commit;

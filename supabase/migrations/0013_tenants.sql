-- 0013_tenants.sql — SaaS multi-tenant : espaces de travail, appartenances, RLS
--
-- Modèle : un utilisateur peut appartenir à plusieurs tenants. Chaque ressource
-- métier porte un `tenant_id`. Les politiques RLS s'appuient sur l'appartenance
-- réelle (table tenant_memberships), jamais sur un identifiant fourni par le
-- navigateur.
--
-- Rejouable : toutes les créations sont idempotentes, le backfill aussi.

begin;

-- ---------------------------------------------------------------------------
-- 1. Tables de tenancy
-- ---------------------------------------------------------------------------

create table if not exists tenants (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    slug        text unique,
    plan        text not null default 'free',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create table if not exists tenant_memberships (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references tenants(id) on delete cascade,
    user_id     uuid not null references profiles(id) on delete cascade,
    role        text not null default 'member'
                check (role in ('owner', 'admin', 'member', 'viewer')),
    created_at  timestamptz not null default now(),
    unique (tenant_id, user_id)
);

create index if not exists ix_tenant_memberships_user on tenant_memberships (user_id);
create index if not exists ix_tenant_memberships_tenant on tenant_memberships (tenant_id);

create table if not exists tenant_settings (
    tenant_id       uuid primary key references tenants(id) on delete cascade,
    locale          text not null default 'fr',
    timezone        text not null default 'Africa/Abidjan',
    voice_language  text not null default 'fr',
    data            jsonb not null default '{}'::jsonb,
    updated_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 2. Backfill : un espace personnel par profil existant
-- ---------------------------------------------------------------------------

insert into tenants (id, name, slug)
select p.id,
       coalesce(nullif(btrim(p.display_name), ''), 'Espace ' || left(p.id::text, 8)),
       'perso-' || left(p.id::text, 8)
from profiles p
where not exists (select 1 from tenants t where t.id = p.id)
on conflict (id) do nothing;

insert into tenant_memberships (tenant_id, user_id, role)
select p.id, p.id, 'owner'
from profiles p
on conflict (tenant_id, user_id) do nothing;

insert into tenant_settings (tenant_id)
select t.id from tenants t
on conflict (tenant_id) do nothing;

-- ---------------------------------------------------------------------------
-- 3. tenant_id sur les ressources métier
-- ---------------------------------------------------------------------------

alter table conversations   add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table messages        add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table tasks           add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table task_steps      add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table executions      add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table memories        add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table approvals       add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table integrations    add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table audit_logs      add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table notifications   add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table documents       add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table evidence        add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table voice_sessions  add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table device_connectors add column if not exists tenant_id uuid references tenants(id) on delete cascade;
alter table device_commands add column if not exists tenant_id uuid references tenants(id) on delete cascade;

-- Backfill direct depuis user_id
update conversations c set tenant_id = c.user_id where c.tenant_id is null and c.user_id is not null;
update tasks t set tenant_id = t.user_id where t.tenant_id is null and t.user_id is not null;
update memories m set tenant_id = m.user_id where m.tenant_id is null and m.user_id is not null;
update approvals a set tenant_id = a.user_id where a.tenant_id is null and a.user_id is not null;
update integrations i set tenant_id = i.user_id where i.tenant_id is null and i.user_id is not null;
update audit_logs l set tenant_id = l.user_id where l.tenant_id is null and l.user_id is not null;
update notifications n set tenant_id = n.user_id where n.tenant_id is null and n.user_id is not null;
update documents d set tenant_id = d.user_id where d.tenant_id is null and d.user_id is not null;
update evidence e set tenant_id = e.user_id where e.tenant_id is null and e.user_id is not null;
update voice_sessions v set tenant_id = v.user_id where v.tenant_id is null and v.user_id is not null;
update device_connectors c set tenant_id = c.user_id where c.tenant_id is null and c.user_id is not null;
update device_commands c set tenant_id = c.user_id where c.tenant_id is null and c.user_id is not null;

-- Backfill depuis le parent
update messages m set tenant_id = c.tenant_id
from conversations c
where m.conversation_id = c.id and m.tenant_id is null;

update task_steps s set tenant_id = t.tenant_id
from tasks t
where s.task_id = t.id and s.tenant_id is null;

update executions x set tenant_id = t.tenant_id
from tasks t
where x.task_id = t.id and x.tenant_id is null;

-- Index de lecture par tenant
create index if not exists ix_conversations_tenant_created on conversations (tenant_id, created_at desc);
create index if not exists ix_messages_tenant_created on messages (tenant_id, created_at desc);
create index if not exists ix_tasks_tenant_created on tasks (tenant_id, created_at desc);
create index if not exists ix_documents_tenant_created on documents (tenant_id, created_at desc);
create index if not exists ix_memories_tenant on memories (tenant_id);
create index if not exists ix_notifications_tenant_created on notifications (tenant_id, created_at desc);
create index if not exists ix_evidence_tenant on evidence (tenant_id);

-- ---------------------------------------------------------------------------
-- 4. Fonctions d'autorisation (SECURITY DEFINER : évite la récursion RLS)
-- ---------------------------------------------------------------------------

create or replace function public.is_tenant_member(t uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1 from tenant_memberships m
        where m.tenant_id = t and m.user_id = auth.uid()
    );
$$;

create or replace function public.tenant_role(t uuid)
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select m.role from tenant_memberships m
    where m.tenant_id = t and m.user_id = auth.uid()
    limit 1;
$$;

-- Écriture : owner et admin. Les membres peuvent créer et modifier leurs
-- propres conversations/messages, lus par le rôle applicatif.
create or replace function public.can_write_tenant(t uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1 from tenant_memberships m
        where m.tenant_id = t and m.user_id = auth.uid()
          and m.role in ('owner', 'admin', 'member')
    );
$$;

create or replace function public.can_manage_tenant(t uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select exists (
        select 1 from tenant_memberships m
        where m.tenant_id = t and m.user_id = auth.uid()
          and m.role in ('owner', 'admin')
    );
$$;

-- ---------------------------------------------------------------------------
-- 5. Remplacement des politiques : appartenance au tenant, pas user_id
-- ---------------------------------------------------------------------------

do $$
declare r record;
begin
    for r in select tablename, policyname from pg_policies where schemaname = 'public'
    loop
        execute format('drop policy if exists %I on public.%I', r.policyname, r.tablename);
    end loop;
end $$;

-- Tenants : on voit ceux dont on est membre ; owner/admin peuvent modifier.
create policy tenants_select on tenants
    for select to authenticated using (is_tenant_member(id));
create policy tenants_update on tenants
    for update to authenticated using (can_manage_tenant(id)) with check (can_manage_tenant(id));

-- Appartenances : on voit les siennes et celles de ses tenants (owner/admin).
create policy memberships_select on tenant_memberships
    for select to authenticated
    using (user_id = auth.uid() or is_tenant_member(tenant_id));
create policy memberships_manage on tenant_memberships
    for all to authenticated
    using (can_manage_tenant(tenant_id)) with check (can_manage_tenant(tenant_id));

create policy tenant_settings_select on tenant_settings
    for select to authenticated using (is_tenant_member(tenant_id));
create policy tenant_settings_update on tenant_settings
    for update to authenticated using (can_manage_tenant(tenant_id)) with check (can_manage_tenant(tenant_id));

-- Profils : soi-même, plus les membres de ses tenants (affichage des auteurs).
create policy profiles_select on profiles
    for select to authenticated
    using (
        id = auth.uid()
        or exists (
            select 1 from tenant_memberships mine
            join tenant_memberships other on other.tenant_id = mine.tenant_id
            where mine.user_id = auth.uid() and other.user_id = profiles.id
        )
    );
create policy profiles_insert on profiles
    for insert to authenticated with check (id = auth.uid());
create policy profiles_update on profiles
    for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

-- Ressources tenant-scoped : lecture par appartenance, écriture par rôle.
do $$
declare t text;
begin
    foreach t in array array[
        'conversations', 'messages', 'tasks', 'task_steps', 'executions',
        'memories', 'approvals', 'integrations', 'documents', 'evidence',
        'voice_sessions', 'device_connectors', 'device_commands'
    ]
    loop
        execute format(
            'create policy %I on public.%I for select to authenticated using (is_tenant_member(tenant_id))',
            t || '_select_tenant', t);
        execute format(
            'create policy %I on public.%I for insert to authenticated with check (is_tenant_member(tenant_id) and can_write_tenant(tenant_id))',
            t || '_insert_tenant', t);
        execute format(
            'create policy %I on public.%I for update to authenticated using (is_tenant_member(tenant_id) and can_write_tenant(tenant_id)) with check (is_tenant_member(tenant_id))',
            t || '_update_tenant', t);
        execute format(
            'create policy %I on public.%I for delete to authenticated using (is_tenant_member(tenant_id) and can_write_tenant(tenant_id))',
            t || '_delete_tenant', t);
    end loop;
end $$;

-- Journal d'audit : lecture par les gestionnaires du tenant, écriture ouverte
-- aux membres (l'application journalise ses propres actions).
create policy audit_logs_select on audit_logs
    for select to authenticated using (can_manage_tenant(tenant_id));
create policy audit_logs_insert on audit_logs
    for insert to authenticated with check (is_tenant_member(tenant_id));

create policy notifications_select on notifications
    for select to authenticated using (is_tenant_member(tenant_id) and user_id = auth.uid());
create policy notifications_update on notifications
    for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Catalogue de compétences : lisible par tout utilisateur authentifié.
create policy skills_select on skills for select to authenticated using (true);
create policy skill_versions_select on skill_versions for select to authenticated using (true);

-- Le catalogue est global (pas de données client). Le rôle applicatif doit
-- pouvoir le synchroniser au démarrage, avant qu'une identité utilisateur
-- existe : deux politiques dédiées évitent de lui ouvrir le reste du schéma.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'kwes_app') then
        execute 'create policy skills_app_write on skills for all to kwes_app using (true) with check (true)';
        execute 'create policy skill_versions_app_write on skill_versions for all to kwes_app using (true) with check (true)';
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- 6. FORCE ROW LEVEL SECURITY (le propriétaire des tables n'échappe plus)
-- ---------------------------------------------------------------------------

do $$
declare t text;
begin
    foreach t in array array[
        'tenants', 'tenant_memberships', 'tenant_settings', 'profiles',
        'conversations', 'messages', 'tasks', 'task_steps', 'executions',
        'memories', 'approvals', 'integrations', 'audit_logs', 'notifications',
        'documents', 'evidence', 'voice_sessions', 'device_connectors',
        'device_commands', 'skills', 'skill_versions'
    ]
    loop
        execute format('alter table public.%I enable row level security', t);
        execute format('alter table public.%I force row level security', t);
    end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 7. Droits du rôle applicatif
-- ---------------------------------------------------------------------------

grant usage on schema public to authenticated;
grant usage on schema auth to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;

commit;

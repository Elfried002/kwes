-- 0007 — Connecteurs d'appareil : découverte de capacités, permissions, commandes.
-- Le moteur d'orchestration ne connaît que des capacités ; les appareils sont
-- enregistrés séparément et authentifiés par un jeton dédié (hash SHA-256).

begin;

create table if not exists public.device_connectors (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid not null references auth.users(id) on delete cascade,
    connector_id      text not null,
    platform          text not null check (platform in ('android','ios','windows','linux','macos','cloud')),
    connector_version text not null default '0.1.0',
    capabilities      jsonb not null default '[]'::jsonb,
    permissions       jsonb not null default '{}'::jsonb,
    status            text not null default 'active' check (status in ('active','offline','revoked')),
    token_hash        text not null,
    last_seen_at      timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    unique (user_id, connector_id)
);

create index if not exists idx_device_connectors_user on public.device_connectors (user_id);
create unique index if not exists idx_device_connectors_token on public.device_connectors (token_hash);

create table if not exists public.device_commands (
    id              uuid primary key default gen_random_uuid(),
    connector_id    uuid not null references public.device_connectors(id) on delete cascade,
    user_id         uuid not null references auth.users(id) on delete cascade,
    capability      text not null,
    payload         jsonb not null default '{}'::jsonb,
    status          text not null default 'queued'
                    check (status in ('queued','sent','succeeded','failed','expired','refused')),
    result          jsonb,
    error_code      text,
    approval_id     uuid references public.approvals(id) on delete set null,
    idempotency_key text,
    created_at      timestamptz not null default now(),
    completed_at    timestamptz
);

create index if not exists idx_device_commands_connector on public.device_commands (connector_id, status);
create index if not exists idx_device_commands_user on public.device_commands (user_id);

alter table public.device_connectors enable row level security;
alter table public.device_commands enable row level security;

drop policy if exists device_connectors_select_own on public.device_connectors;
create policy device_connectors_select_own on public.device_connectors
    for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists device_connectors_insert_own on public.device_connectors;
create policy device_connectors_insert_own on public.device_connectors
    for insert to authenticated with check (user_id = (select auth.uid()));

drop policy if exists device_connectors_update_own on public.device_connectors;
create policy device_connectors_update_own on public.device_connectors
    for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

drop policy if exists device_connectors_delete_own on public.device_connectors;
create policy device_connectors_delete_own on public.device_connectors
    for delete to authenticated using (user_id = (select auth.uid()));

drop policy if exists device_commands_select_own on public.device_commands;
create policy device_commands_select_own on public.device_commands
    for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists device_commands_insert_own on public.device_commands;
create policy device_commands_insert_own on public.device_commands
    for insert to authenticated with check (user_id = (select auth.uid()));

commit;

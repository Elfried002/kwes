-- 0019 — Quotas par tenant, suspension d'espace, désactivation d'agent

create table if not exists tenant_quotas (
    tenant_id                    uuid primary key references tenants (id) on delete cascade,
    max_concurrent_missions      integer not null default 2  check (max_concurrent_missions between 1 and 50),
    max_missions_per_day         integer not null default 50 check (max_missions_per_day between 1 and 10000),
    max_tool_calls_per_mission   integer not null default 24 check (max_tool_calls_per_mission between 1 and 500),
    max_llm_tokens_per_month     integer not null default 2000000 check (max_llm_tokens_per_month >= 0),
    updated_at                   timestamptz not null default now()
);

alter table tenant_quotas enable row level security;
alter table tenant_quotas force row level security;
create policy tenant_quotas_read on tenant_quotas
    for select using (is_tenant_member(tenant_id));
create policy tenant_quotas_service on tenant_quotas
    for all to kwes_app using (true) with check (true);
grant select, insert, update, delete on tenant_quotas to kwes_app;
-- Le quota par défaut est créé à la première mission : le rôle applicatif a
-- besoin d'insérer et de mettre à jour sa propre ligne (RLS par appartenance).
grant select, insert, update on tenant_quotas to authenticated;
-- Une politique dédiée au rôle `authenticated` est indispensable : la politique
-- « service » ne s'applique qu'à kwes_app, et l'API bascule en authenticated.
create policy tenant_quotas_member_write on tenant_quotas
    for all to authenticated using (is_tenant_member(tenant_id))
    with check (is_tenant_member(tenant_id));

-- Suspension d'un espace (admin). Null = actif.
alter table tenants add column if not exists suspended_at timestamptz;
alter table tenants add column if not exists suspended_reason text;

-- Désactivation d'un agent au niveau plateforme (kill-switch auditable).
create table if not exists agent_overrides (
    agent_id    text primary key,
    enabled     boolean not null default true,
    reason      text,
    updated_by  uuid,
    updated_at  timestamptz not null default now()
);

alter table agent_overrides enable row level security;
alter table agent_overrides force row level security;
create policy agent_overrides_read on agent_overrides for select using (true);
create policy agent_overrides_write on agent_overrides
    for all to kwes_app using (true) with check (true);
grant select, insert, update, delete on agent_overrides to kwes_app;
grant select on agent_overrides to authenticated;

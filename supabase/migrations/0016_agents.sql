-- 0016 — Registre d'agents, capacités, exécutions et messages inter-agents
--
-- PRÉPARÉE, NON APPLIQUÉE. Aucune exécution de cette migration n'a eu lieu en
-- production : elle attend la validation d'Elfried (voir
-- docs/integration/KWES_AGENTIC_INTEGRATION_ROADMAP.md).
--
-- Modèle :
--   * `agents` et `agent_capabilities` sont un catalogue global (comme `skills`) :
--     les définitions ne sont pas propres à un tenant ;
--   * `agent_runs` et `agent_messages` sont des données d'exécution, donc
--     strictement isolées par tenant ;
--   * un agent ne s'exécute jamais avec BYPASSRLS : le contexte est posé par tâche.

-- --------------------------------------------------------------------------
-- Catalogue : agents
-- --------------------------------------------------------------------------
create table if not exists agents (
    id              uuid primary key default gen_random_uuid(),
    agent_id        text not null unique,
    display_name    text not null,
    agent_type      text not null check (agent_type in ('orchestrator', 'specialist')),
    domain          text,
    version         text not null,
    package_version text not null,
    status          text not null default 'defined_not_activated'
                    check (status in ('defined_not_activated', 'tested', 'active', 'retired')),
    config          jsonb not null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint agents_agent_id_format check (agent_id like 'kwes.%')
);

create index if not exists idx_agents_status on agents (status);

-- --------------------------------------------------------------------------
-- Catalogue : capacités et niveaux d'approbation
-- --------------------------------------------------------------------------
create table if not exists agent_capabilities (
    agent_id       uuid not null references agents (id) on delete cascade,
    tool_id        text not null,
    tool_status    text not null check (tool_status in ('implemented', 'declared', 'retired')),
    approval_level text not null check (approval_level in ('A0', 'A1', 'A2', 'A3', 'A4')),
    approval_mode  text not null check (approval_mode in ('none', 'policy_checked', 'explicit', 'strong')),
    engine_risk    text check (engine_risk in ('R0', 'R1', 'R2', 'R3', 'R4')),
    created_at     timestamptz not null default now(),
    primary key (agent_id, tool_id)
);

-- Un outil A3/A4 ne peut pas être associé à un risque moteur inférieur à R2/R3 :
-- c'est la garantie « aucune action ne descend de niveau par erreur de table ».
alter table agent_capabilities
    drop constraint if exists agent_capabilities_no_downgrade;
alter table agent_capabilities
    add constraint agent_capabilities_no_downgrade check (
        (approval_level in ('A0', 'A1') and (engine_risk is null or engine_risk in ('R0', 'R1')))
        or (approval_level = 'A2' and (engine_risk is null or engine_risk in ('R1', 'R2')))
        or (approval_level = 'A3' and engine_risk in ('R2'))
        or (approval_level = 'A4' and engine_risk in ('R3', 'R4'))
    );

-- --------------------------------------------------------------------------
-- Exécution : une ligne par tâche confiée à un agent
-- --------------------------------------------------------------------------
create table if not exists agent_runs (
    id               uuid primary key default gen_random_uuid(),
    tenant_id        uuid not null references tenants (id) on delete cascade,
    task_id          uuid references tasks (id) on delete set null,
    mission_id       uuid,
    agent_id         text not null,
    parent_run_id    uuid references agent_runs (id) on delete set null,
    autonomy_level   text not null check (autonomy_level in ('A0', 'A1', 'A2', 'A3', 'A4')),
    status           text not null default 'queued'
                     check (status in ('queued', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled')),
    language         text check (language in ('fr', 'en')),
    tool_calls       integer not null default 0,
    input_tokens     integer,
    output_tokens    integer,
    cost_eur         numeric(10, 4),
    started_at       timestamptz not null default now(),
    ended_at         timestamptz,
    duration_ms      integer,
    error_code       text,
    result           jsonb,
    created_at       timestamptz not null default now()
);

create index if not exists idx_agent_runs_tenant on agent_runs (tenant_id, started_at desc);
create index if not exists idx_agent_runs_task on agent_runs (task_id);
create index if not exists idx_agent_runs_agent on agent_runs (agent_id, status);

-- --------------------------------------------------------------------------
-- Messages inter-agents (contrats de tâche et résultats)
-- --------------------------------------------------------------------------
create table if not exists agent_messages (
    id            uuid primary key default gen_random_uuid(),
    tenant_id     uuid not null references tenants (id) on delete cascade,
    mission_id    uuid,
    task_id       uuid references tasks (id) on delete set null,
    from_agent    text not null,
    to_agent      text not null,
    kind          text not null check (kind in ('task', 'result', 'clarification')),
    payload       jsonb not null,
    created_at    timestamptz not null default now()
);

create index if not exists idx_agent_messages_mission on agent_messages (tenant_id, mission_id, created_at);

-- --------------------------------------------------------------------------
-- RLS
-- --------------------------------------------------------------------------
alter table agents             enable row level security;
alter table agent_capabilities enable row level security;
alter table agent_runs         enable row level security;
alter table agent_messages     enable row level security;

-- Catalogue : lecture pour tous les utilisateurs authentifiés, écriture réservée
-- au rôle applicatif (le catalogue est alimenté par le déploiement).
drop policy if exists agents_read on agents;
create policy agents_read on agents
    for select using (true);

drop policy if exists agents_write on agents;
create policy agents_write on agents
    for all to kwes_app using (true) with check (true);

drop policy if exists agent_capabilities_read on agent_capabilities;
create policy agent_capabilities_read on agent_capabilities
    for select using (true);

drop policy if exists agent_capabilities_write on agent_capabilities;
create policy agent_capabilities_write on agent_capabilities
    for all to kwes_app using (true) with check (true);

-- Données d'exécution : strictement par tenant.
drop policy if exists agent_runs_tenant on agent_runs;
create policy agent_runs_tenant on agent_runs
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

drop policy if exists agent_messages_tenant on agent_messages;
create policy agent_messages_tenant on agent_messages
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

-- --------------------------------------------------------------------------
-- Instrumentation : une ligne par appel LLM (tokens réels, modèle, durée)
-- --------------------------------------------------------------------------
create table if not exists llm_usage (
    id            uuid primary key default gen_random_uuid(),
    tenant_id     uuid references tenants (id) on delete cascade,
    mission_id    uuid,
    agent_id      text,
    model         text not null,
    provider      text not null default 'google',
    purpose       text not null default 'chat',
    input_tokens  integer,
    output_tokens integer,
    duration_ms   integer not null default 0,
    source        text not null default 'provider',
    cost_eur      numeric(12, 6),
    created_at    timestamptz not null default now()
);

create index if not exists idx_llm_usage_tenant on llm_usage (tenant_id, created_at desc);
create index if not exists idx_llm_usage_mission on llm_usage (mission_id);

alter table llm_usage enable row level security;

drop policy if exists llm_usage_tenant on llm_usage;
create policy llm_usage_tenant on llm_usage
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

alter table llm_usage force row level security;

-- Droits explicites : le rôle applicatif bascule en `authenticated` pendant une
-- requête (voir app/db/rls.py), et `authenticated` doit pouvoir lire/écrire les
-- lignes que les politiques autorisent. Sans ces GRANT, la migration crée des
-- tables inutilisables par l'API (constaté en staging le 19/11/2026).
grant select, insert, update, delete on agents             to kwes_app, authenticated;
grant select, insert, update, delete on agent_capabilities to kwes_app, authenticated;
grant select, insert, update, delete on agent_runs         to kwes_app, authenticated;
grant select, insert, update, delete on agent_messages     to kwes_app, authenticated;
grant select, insert, update, delete on llm_usage          to kwes_app, authenticated;

alter table agent_runs     force row level security;
alter table agent_messages force row level security;
alter table agents         force row level security;
alter table agent_capabilities force row level security;

-- 0017 — Socle agentique étendu : tâches déléguées, journal, connecteurs, coûts
--
-- Appliquée en STAGING uniquement. La production attend une validation distincte.
--
-- Modèle de classement des tables :
--   * catalogue global (lecture pour tous, écriture réservée) :
--       connector_catalog, cost_rates
--   * tenant-scoped (RLS par appartenance) :
--       agent_tasks, run_events, tool_invocations, tenant_connections, oauth_states
--   * système (pas de tenant, accès service) :
--       platform_roles, admin_alerts

-- --------------------------------------------------------------------------
-- Tâches déléguées à un spécialiste (un nœud du graphe de mission)
-- --------------------------------------------------------------------------
create table if not exists agent_tasks (
    id                uuid primary key default gen_random_uuid(),
    tenant_id         uuid not null references tenants (id) on delete cascade,
    mission_id        uuid not null references tasks (id) on delete cascade,
    agent_id          text not null,
    seq               integer not null default 0,
    objective         text not null,
    expected_output   text not null,
    acceptance        jsonb not null default '[]'::jsonb,
    status            text not null default 'pending'
                      check (status in ('pending', 'ready', 'claimed', 'running',
                                        'waiting_approval', 'retry_wait', 'completed',
                                        'failed', 'cancelled', 'blocked', 'timed_out')),
    autonomy_level    text not null default 'A1' check (autonomy_level in ('A0','A1','A2','A3','A4')),
    depends_on        jsonb not null default '[]'::jsonb,
    allowed_tools     jsonb not null default '[]'::jsonb,
    max_tool_calls    integer not null default 12 check (max_tool_calls between 1 and 100),
    max_llm_turns     integer not null default 4 check (max_llm_turns between 1 and 20),
    deadline_seconds  integer not null default 180 check (deadline_seconds between 1 and 600),
    attempt           integer not null default 0,
    idempotency_key   text not null,
    result_summary    text,
    evidence          jsonb not null default '[]'::jsonb,
    limitations       jsonb not null default '[]'::jsonb,
    error_code        text,
    error_message     text,
    started_at        timestamptz,
    finished_at       timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    unique (mission_id, idempotency_key)
);

create index if not exists idx_agent_tasks_mission on agent_tasks (mission_id);
create index if not exists idx_agent_tasks_tenant_status on agent_tasks (tenant_id, status);

-- --------------------------------------------------------------------------
-- Journal d'exécution (append-only côté application)
-- --------------------------------------------------------------------------
create table if not exists run_events (
    id              bigserial primary key,
    tenant_id       uuid not null references tenants (id) on delete cascade,
    mission_id      uuid references tasks (id) on delete cascade,
    agent_task_id   uuid references agent_tasks (id) on delete cascade,
    agent_id        text,
    tool_id         text,
    event_type      text not null,
    status          text,
    duration_ms     integer,
    attempt         integer not null default 0,
    correlation_id  text,
    idempotency_key text,
    approval_id     uuid,
    usage_id        uuid,
    evidence_ref    text,
    error_code      text,
    safe_metadata   jsonb not null default '{}'::jsonb,
    occurred_at     timestamptz not null default now()
);

create index if not exists idx_run_events_mission on run_events (mission_id, occurred_at);
create index if not exists idx_run_events_tenant on run_events (tenant_id, occurred_at desc);
create index if not exists idx_run_events_type on run_events (event_type);

-- --------------------------------------------------------------------------
-- Appels d'outils (preuve d'exécution, arguments expurgés)
-- --------------------------------------------------------------------------
create table if not exists tool_invocations (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references tenants (id) on delete cascade,
    mission_id      uuid references tasks (id) on delete cascade,
    agent_task_id   uuid references agent_tasks (id) on delete cascade,
    agent_id        text,
    tool_id         text not null,
    tool_version    text,
    arguments       jsonb not null default '{}'::jsonb,
    status          text not null check (status in ('ok', 'error', 'denied', 'timeout')),
    error_code      text,
    duration_ms     integer,
    output_digest   text,
    evidence_ref    text,
    created_at      timestamptz not null default now()
);

create index if not exists idx_tool_invocations_mission on tool_invocations (mission_id, created_at);
create index if not exists idx_tool_invocations_tenant on tool_invocations (tenant_id, created_at desc);

-- --------------------------------------------------------------------------
-- Catalogue des connecteurs (global)
-- --------------------------------------------------------------------------
create table if not exists connector_catalog (
    provider_id     text primary key,
    display_name    text not null,
    category        text not null,
    auth_mode       text not null check (auth_mode in ('oauth2', 'oauth2_pkce', 'api_key', 'bot_token', 'none')),
    status          text not null default 'needs_configuration'
                    check (status in ('available', 'needs_configuration', 'provider_review', 'unavailable')),
    capabilities    jsonb not null default '[]'::jsonb,
    scopes          jsonb not null default '[]'::jsonb,
    limits          text,
    docs_url        text,
    manifest        jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- Connexions d'un tenant à un fournisseur (jamais de secret en clair)
-- --------------------------------------------------------------------------
create table if not exists tenant_connections (
    id                uuid primary key default gen_random_uuid(),
    tenant_id         uuid not null references tenants (id) on delete cascade,
    owner_user_id     uuid not null,
    provider_id       text not null references connector_catalog (provider_id) on delete cascade,
    status            text not null default 'pending'
                      check (status in ('pending', 'active', 'expired', 'error', 'revoked')),
    scopes            jsonb not null default '[]'::jsonb,
    secret_ref        text,
    account_label     text,
    external_id       text,
    last_checked_at   timestamptz,
    last_error        text,
    expires_at        timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    unique (tenant_id, provider_id, owner_user_id)
);

create index if not exists idx_tenant_connections_tenant on tenant_connections (tenant_id, status);

-- --------------------------------------------------------------------------
-- États OAuth (anti-CSRF, PKCE, anti-replay)
-- --------------------------------------------------------------------------
create table if not exists oauth_states (
    state           text primary key,
    tenant_id       uuid not null references tenants (id) on delete cascade,
    user_id         uuid not null,
    provider_id     text not null,
    code_verifier   text,
    redirect_to     text,
    consumed        boolean not null default false,
    created_at      timestamptz not null default now(),
    expires_at      timestamptz not null default now() + interval '10 minutes'
);

create index if not exists idx_oauth_states_tenant on oauth_states (tenant_id, created_at desc);

-- --------------------------------------------------------------------------
-- Tarifs versionnés (aucun tarif inventé : uniquement draft/approved saisis)
-- --------------------------------------------------------------------------
create table if not exists cost_rates (
    id              uuid primary key default gen_random_uuid(),
    provider        text not null,
    model           text not null,
    unit            text not null default 'token',
    input_per_million   numeric(12,6),
    output_per_million  numeric(12,6),
    currency        text not null default 'USD',
    effective_from  date not null,
    source_url      text,
    status          text not null default 'draft' check (status in ('draft', 'approved', 'retired')),
    approved_by     uuid,
    approved_at     timestamptz,
    created_at      timestamptz not null default now(),
    unique (provider, model, unit, effective_from)
);

-- --------------------------------------------------------------------------
-- Rôles de plateforme (administration) — jamais modifiables par un agent
-- --------------------------------------------------------------------------
create table if not exists platform_roles (
    user_id     uuid primary key,
    role        text not null check (role in ('super_admin', 'ops_admin', 'support_readonly',
                                              'security_auditor', 'billing_admin')),
    granted_by  uuid,
    granted_at  timestamptz not null default now(),
    note        text
);

-- --------------------------------------------------------------------------
-- Alertes d'exploitation
-- --------------------------------------------------------------------------
create table if not exists admin_alerts (
    id          uuid primary key default gen_random_uuid(),
    severity    text not null check (severity in ('info', 'warning', 'critical')),
    source      text not null,
    code        text not null,
    tenant_id   uuid references tenants (id) on delete set null,
    mission_id  uuid references tasks (id) on delete set null,
    message     text not null,
    metadata    jsonb not null default '{}'::jsonb,
    acknowledged_at timestamptz,
    acknowledged_by uuid,
    created_at  timestamptz not null default now()
);

create index if not exists idx_admin_alerts_open on admin_alerts (severity, created_at desc)
    where acknowledged_at is null;

-- --------------------------------------------------------------------------
-- RLS
-- --------------------------------------------------------------------------
alter table agent_tasks        enable row level security;
alter table run_events         enable row level security;
alter table tool_invocations   enable row level security;
alter table tenant_connections enable row level security;
alter table oauth_states       enable row level security;
alter table connector_catalog  enable row level security;
alter table cost_rates         enable row level security;
alter table platform_roles     enable row level security;
alter table admin_alerts       enable row level security;

alter table agent_tasks        force row level security;
alter table run_events         force row level security;
alter table tool_invocations   force row level security;
alter table tenant_connections force row level security;
alter table oauth_states       force row level security;
alter table connector_catalog  force row level security;
alter table cost_rates         force row level security;
alter table platform_roles     force row level security;
alter table admin_alerts       force row level security;

-- Catalogue : lisible par tous les utilisateurs authentifiés, écrit par le service.
create policy connector_catalog_read on connector_catalog
    for select using (true);
create policy connector_catalog_write on connector_catalog
    for all to kwes_app using (true) with check (true);

create policy cost_rates_read on cost_rates
    for select using (true);
create policy cost_rates_write on cost_rates
    for all to kwes_app using (true) with check (true);

-- Données d'exécution : strictement par tenant.
create policy agent_tasks_tenant on agent_tasks
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

create policy run_events_tenant on run_events
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

create policy tool_invocations_tenant on tool_invocations
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

create policy tenant_connections_tenant on tenant_connections
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

create policy oauth_states_tenant on oauth_states
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

-- Rôles de plateforme : un utilisateur voit le sien ; le service gère le reste.
create policy platform_roles_self on platform_roles
    for select using (user_id = auth.uid());
create policy platform_roles_service on platform_roles
    for all to kwes_app using (true) with check (true);

-- Alertes : service uniquement pour l'écriture, lecture par le service admin.
create policy admin_alerts_service on admin_alerts
    for all to kwes_app using (true) with check (true);

-- --------------------------------------------------------------------------
-- Droits du rôle applicatif et du rôle `authenticated`
-- --------------------------------------------------------------------------
grant select, insert, update, delete on
    agent_tasks, run_events, tool_invocations, tenant_connections, oauth_states,
    connector_catalog, cost_rates, platform_roles, admin_alerts
    to kwes_app;

grant usage, select on all sequences in schema public to kwes_app;

grant select, insert, update, delete on
    agent_tasks, run_events, tool_invocations, tenant_connections, oauth_states
    to authenticated;
-- Sans cela, toute écriture échoue : `run_events` utilise une séquence et le
-- rôle applicatif bascule en `authenticated` pendant les requêtes (constaté en
-- staging : « permission denied for sequence run_events_id_seq »).
grant usage, select on all sequences in schema public to authenticated;
grant select on connector_catalog, cost_rates to authenticated;

-- 0018 — Coffre de connecteurs (chiffrement au repos)

create table if not exists connector_secrets (
    tenant_id   uuid not null references tenants (id) on delete cascade,
    ref         text not null,
    provider_id text not null,
    ciphertext  text not null,
    updated_at  timestamptz not null default now(),
    primary key (tenant_id, ref)
);

alter table connector_secrets enable row level security;
alter table connector_secrets force row level security;

create policy connector_secrets_tenant on connector_secrets
    for all using (is_tenant_member(tenant_id)) with check (is_tenant_member(tenant_id));

grant select, insert, update, delete on connector_secrets to kwes_app;
grant select, insert, update, delete on connector_secrets to authenticated;

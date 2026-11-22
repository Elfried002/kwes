-- 0021 — État de la phase de découverte (première conversation)
--
-- La séquence de présentation ne doit se jouer qu'une fois par utilisateur :
-- elle s'arrête dès qu'un fait durable existe, et ne se rejoue pas à chaque
-- nouvelle conversation. L'état est donc persisté hors des messages.
--
-- Une ligne par utilisateur (clé primaire = profiles.id), tenant_id facultatif
-- pour rester lisible hors requête. Aucune donnée métier : seulement l'étape
-- (0..3) et les horodatages de fin.
--
-- Idempotent : peut être rejouée.

begin;

create table if not exists public.user_onboarding (
    user_id      uuid primary key references public.profiles (id) on delete cascade,
    tenant_id    uuid references public.tenants (id) on delete cascade,
    step         smallint not null default 0 check (step between 0 and 3),
    completed_at timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists ix_user_onboarding_tenant on public.user_onboarding (tenant_id);

alter table public.user_onboarding enable row level security;
alter table public.user_onboarding force row level security;

-- Un utilisateur ne lit et n'écrit que sa propre ligne. L'API bascule en
-- `authenticated` : la politique doit viser ce rôle explicitement.
drop policy if exists user_onboarding_own on public.user_onboarding;
create policy user_onboarding_own on public.user_onboarding
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

grant select, insert, update on public.user_onboarding to authenticated;

commit;

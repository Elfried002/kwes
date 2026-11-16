-- P1 : registre de preuves.
-- Une ligne = une lecture réussie (HTML rendu ou PDF lu), pas une URL trouvée.

create table if not exists public.evidence (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    task_id uuid references public.tasks(id) on delete set null,
    url text not null,
    canonical_url text not null,
    domain varchar(255) not null,
    title varchar(500),
    excerpt text not null,
    content text,
    content_hash varchar(64) not null,
    provider varchar(64) not null,
    extraction_status varchar(24) not null default 'ok',
    published_at timestamptz,
    fetched_at timestamptz not null default now(),
    provenance jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists evidence_user_fetched_idx on public.evidence (user_id, fetched_at desc);
create index if not exists evidence_user_canonical_idx on public.evidence (user_id, canonical_url);
create index if not exists evidence_domain_idx on public.evidence (domain);
create index if not exists evidence_task_idx on public.evidence (task_id);
create unique index if not exists evidence_user_hash_uidx on public.evidence (user_id, content_hash);

alter table public.evidence enable row level security;

drop policy if exists evidence_select_own on public.evidence;
create policy evidence_select_own on public.evidence
    for select using (user_id = auth.uid());

drop policy if exists evidence_insert_own on public.evidence;
create policy evidence_insert_own on public.evidence
    for insert with check (user_id = auth.uid());

drop policy if exists evidence_delete_own on public.evidence;
create policy evidence_delete_own on public.evidence
    for delete using (user_id = auth.uid());

comment on table public.evidence is
    'Preuves de lecture (P1) : contenu réellement récupéré, empreinte, provenance.';

-- 0008 — Documents produits par l'agent (texte intégral en base).
-- Contenu privé : RLS par utilisateur, aucune lecture anonyme, aucune politique
-- « always true ». La suppression du profil efface les documents.

begin;

create table if not exists public.documents (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    title      text not null check (char_length(title) between 1 and 200),
    format     text not null default 'markdown' check (format in ('markdown','text')),
    content    text not null check (char_length(content) between 1 and 200000),
    chars      integer not null default 0,
    source     text not null default 'agent' check (source in ('agent','user')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_documents_user_created
    on public.documents (user_id, created_at desc);

alter table public.documents enable row level security;

drop policy if exists documents_select_own on public.documents;
create policy documents_select_own on public.documents
    for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists documents_insert_own on public.documents;
create policy documents_insert_own on public.documents
    for insert to authenticated with check (user_id = (select auth.uid()));

drop policy if exists documents_update_own on public.documents;
create policy documents_update_own on public.documents
    for update to authenticated using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

drop policy if exists documents_delete_own on public.documents;
create policy documents_delete_own on public.documents
    for delete to authenticated using (user_id = (select auth.uid()));

commit;

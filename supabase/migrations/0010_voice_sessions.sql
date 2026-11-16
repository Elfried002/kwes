-- 0010 — Sessions vocales Gemini : durée, volume audio, coût estimé.
-- Les montants sont des estimations aux tarifs publiés, jamais une facture.

begin;

create table if not exists public.voice_sessions (
    id                 uuid primary key default gen_random_uuid(),
    user_id            uuid not null references auth.users(id) on delete cascade,
    model              text not null,
    voice              text not null,
    language           text,
    started_at         timestamptz not null default now(),
    ended_at           timestamptz,
    seconds            double precision not null default 0,
    audio_in_seconds   double precision not null default 0,
    audio_out_seconds  double precision not null default 0,
    turns              integer not null default 0,
    estimated_usd      double precision not null default 0,
    close_reason       text
);

create index if not exists idx_voice_sessions_user_started
    on public.voice_sessions (user_id, started_at desc);

alter table public.voice_sessions enable row level security;

drop policy if exists voice_sessions_select_own on public.voice_sessions;
create policy voice_sessions_select_own on public.voice_sessions
    for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists voice_sessions_insert_own on public.voice_sessions;
create policy voice_sessions_insert_own on public.voice_sessions
    for insert to authenticated with check (user_id = (select auth.uid()));

commit;

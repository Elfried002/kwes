-- =============================================================================
-- Kwes — 0001_init.sql
-- Schéma initial : 13 tables du modèle de données (docs/06-data/DATA_MODEL.md).
--
-- Cible   : PostgreSQL 15+ (Supabase managé, ou image pgvector/pgvector:pg16).
-- Auteur  : lot infrastructure — 2026-11-16.
--
-- Règles appliquées :
--   * PK UUID (gen_random_uuid, pgcrypto), horodatages `timestamptz` UTC ;
--   * `user_id` sur toutes les données privées ;
--   * contraintes CHECK sur les statuts (contrat CONTRACTS.md §Statuts) ;
--   * index sur user_id / conversation_id / task_id / status / created_at ;
--   * pgvector + `memories.embedding vector(1536)` + index HNSW cosinus ;
--   * triggers `updated_at` (fonction public.set_updated_at) ;
--   * `handle_new_user` : profil auto-créé à l'inscription Supabase ;
--   * idempotent : IF NOT EXISTS partout, triggers recréés proprement.
--
-- Le script est transactionnel : tout échoue ensemble, rien à moitié appliqué.
-- =============================================================================

begin;

-- `extensions` n'existe pas sur un PostgreSQL nu : le search_path tolère un
-- schéma absent, il couvre donc les deux cas (Supabase = public, extensions).
set local search_path = public, extensions;

create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists vector;     -- pgvector (memories.embedding)

-- -----------------------------------------------------------------------------
-- 1. profiles
--    id = auth.users.id (1-1). Le FK est ajouté plus bas, conditionnellement,
--    pour que la migration reste applicable sur un PostgreSQL sans schéma auth.
-- -----------------------------------------------------------------------------
create table if not exists public.profiles (
    id            uuid primary key,
    display_name  text,
    locale        text not null default 'fr',
    timezone      text not null default 'Europe/Paris',
    is_demo       boolean not null default false,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    constraint profiles_display_name_len check (display_name is null or char_length(display_name) between 1 and 120),
    constraint profiles_locale_format check (locale ~ '^[a-z]{2}(-[A-Z]{2})?$')
);

comment on table  public.profiles is 'Profil applicatif, 1-1 avec auth.users.';
comment on column public.profiles.is_demo is 'Marqueur des données de démonstration (CONTRACTS.md règle 5).';

-- -----------------------------------------------------------------------------
-- 2. conversations
-- -----------------------------------------------------------------------------
create table if not exists public.conversations (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null,
    title       text,
    status      text not null default 'active',
    language    text not null default 'fr',
    is_demo     boolean not null default false,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint conversations_status_check check (status in ('active', 'archived', 'deleted')),
    constraint conversations_title_len check (title is null or char_length(title) <= 200)
);

comment on table public.conversations is 'Fil de conversation possédé par un utilisateur.';

-- -----------------------------------------------------------------------------
-- 3. messages
-- -----------------------------------------------------------------------------
create table if not exists public.messages (
    id               uuid primary key default gen_random_uuid(),
    conversation_id  uuid not null,
    user_id          uuid not null,
    role             text not null,
    content          text not null default '',
    content_type     text not null default 'text',
    metadata         jsonb not null default '{}'::jsonb,
    created_at       timestamptz not null default now(),
    constraint messages_role_check check (role in ('user', 'assistant', 'system', 'tool')),
    constraint messages_content_type_check check (content_type in ('text', 'markdown', 'json', 'audio_transcript')),
    constraint messages_conversation_fkey
        foreign key (conversation_id) references public.conversations (id) on delete cascade
);

comment on column public.messages.metadata is 'Métadonnées non sensibles (tokens, mock flag, latence). Jamais de secret.';

-- -----------------------------------------------------------------------------
-- 4. tasks
--    Statuts imposés par CONTRACTS.md §Statuts task.
-- -----------------------------------------------------------------------------
create table if not exists public.tasks (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null,
    conversation_id uuid,
    title           text not null,
    goal            text,
    status          text not null default 'queued',
    priority        smallint not null default 2,
    progress        smallint not null default 0,
    result_summary  text,
    error_code      text,
    is_demo         boolean not null default false,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    started_at      timestamptz,
    completed_at    timestamptz,
    constraint tasks_status_check check (status in (
        'queued', 'planning', 'awaiting_approval', 'running',
        'paused', 'completed', 'failed', 'cancelled'
    )),
    constraint tasks_priority_check check (priority between 0 and 5),
    constraint tasks_progress_check check (progress between 0 and 100),
    constraint tasks_title_len check (char_length(title) between 1 and 300),
    constraint tasks_conversation_fkey
        foreign key (conversation_id) references public.conversations (id) on delete set null,
    constraint tasks_completed_after_started
        check (completed_at is null or started_at is null or completed_at >= started_at)
);

comment on table public.tasks is 'Mission asynchrone exécutée par le worker.';

-- -----------------------------------------------------------------------------
-- 5. task_steps
-- -----------------------------------------------------------------------------
create table if not exists public.task_steps (
    id             uuid primary key default gen_random_uuid(),
    task_id        uuid not null,
    step_key       text not null,
    title          text,
    skill_id       uuid,
    status         text not null default 'pending',
    input_json     jsonb not null default '{}'::jsonb,
    output_json    jsonb not null default '{}'::jsonb,
    depends_on      text[] not null default '{}'::text[],
    attempt_count  smallint not null default 0,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    constraint task_steps_status_check check (status in (
        'pending', 'ready', 'running', 'awaiting_approval',
        'completed', 'failed', 'skipped', 'cancelled'
    )),
    constraint task_steps_attempt_count_check check (attempt_count >= 0),
    constraint task_steps_task_fkey
        foreign key (task_id) references public.tasks (id) on delete cascade,
    constraint task_steps_task_step_key_uniq unique (task_id, step_key)
);

comment on column public.task_steps.depends_on is 'ids de task_steps prérequis (graphe du plan).';

-- -----------------------------------------------------------------------------
-- 6. executions
-- -----------------------------------------------------------------------------
create table if not exists public.executions (
    id               uuid primary key default gen_random_uuid(),
    task_id          uuid not null,
    step_id          uuid,
    tool_name        text not null,
    status           text not null default 'running',
    input_redacted   jsonb not null default '{}'::jsonb,
    output_summary   text,
    duration_ms      integer,
    error_code       text,
    idempotency_key  text,
    started_at       timestamptz not null default now(),
    finished_at      timestamptz,
    constraint executions_status_check check (status in ('running', 'completed', 'failed', 'cancelled')),
    constraint executions_duration_check check (duration_ms is null or duration_ms >= 0),
    constraint executions_task_fkey
        foreign key (task_id) references public.tasks (id) on delete cascade,
    constraint executions_step_fkey
        foreign key (step_id) references public.task_steps (id) on delete set null
);

comment on column public.executions.input_redacted is 'Entrée expurgée : jamais de token, mot de passe ni donnée de paiement.';
comment on column public.executions.idempotency_key is 'Anti-doublon des actions externes (unicité partielle).';

-- -----------------------------------------------------------------------------
-- 7. skills / 8. skill_versions
--    Tables de référence : lecture seule pour les clients authentifiés.
-- -----------------------------------------------------------------------------
create table if not exists public.skills (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    description     text,
    current_version text,
    enabled         boolean not null default true,
    created_at      timestamptz not null default now(),
    constraint skills_name_uniq unique (name),
    constraint skills_name_format check (name ~ '^[a-z][a-z0-9_]{2,63}$')
);

create table if not exists public.skill_versions (
    id             uuid primary key default gen_random_uuid(),
    skill_id       uuid not null,
    version        text not null,
    manifest_json  jsonb not null default '{}'::jsonb,
    artifact_hash  text,
    status         text not null default 'draft',
    created_at     timestamptz not null default now(),
    approved_at    timestamptz,
    constraint skill_versions_status_check check (status in ('draft', 'active', 'deprecated', 'revoked')),
    constraint skill_versions_skill_fkey
        foreign key (skill_id) references public.skills (id) on delete cascade,
    constraint skill_versions_skill_version_uniq unique (skill_id, version),
    constraint skill_versions_version_format check (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$')
);

comment on column public.skill_versions.status is 'Une seule version active par skill est attendue (index partiel ci-dessous).';

-- -----------------------------------------------------------------------------
-- 9. memories (+ pgvector)
-- -----------------------------------------------------------------------------
create table if not exists public.memories (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null,
    category     text not null default 'fact',
    content      text not null,
    source_type  text,
    source_id    uuid,
    confidence   numeric(3, 2) not null default 0.50,
    sensitivity  text not null default 'private',
    embedding    vector(1536),
    is_demo      boolean not null default false,
    expires_at   timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    constraint memories_category_check check (category in (
        'fact', 'preference', 'goal', 'constraint', 'project', 'relationship', 'other'
    )),
    constraint memories_sensitivity_check check (sensitivity in ('public', 'internal', 'private', 'restricted')),
    constraint memories_confidence_check check (confidence >= 0 and confidence <= 1),
    constraint memories_content_len check (char_length(content) between 1 and 8000)
);

comment on column public.memories.embedding is 'Vecteur 1536 dims (text-embedding-3-small / équivalent). NULL = pas encore indexé.';
comment on column public.memories.sensitivity is 'restricted => jamais envoyé au LLM sans masquage.';

-- -----------------------------------------------------------------------------
-- 10. approvals
-- -----------------------------------------------------------------------------
create table if not exists public.approvals (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null,
    task_id       uuid,
    step_id       uuid,
    action_type   text not null,
    payload_hash  text not null,
    summary       text not null default '',
    status        text not null default 'pending',
    expires_at    timestamptz not null default (now() + interval '30 minutes'),
    decided_at    timestamptz,
    created_at    timestamptz not null default now(),
    constraint approvals_status_check check (status in ('pending', 'approved', 'rejected', 'expired')),
    constraint approvals_task_fkey
        foreign key (task_id) references public.tasks (id) on delete cascade,
    constraint approvals_step_fkey
        foreign key (step_id) references public.task_steps (id) on delete set null,
    constraint approvals_decided_consistency check (
        (status = 'pending' and decided_at is null) or (status <> 'pending')
    )
);

comment on column public.approvals.payload_hash is 'Empreinte du payload approuvé : rejoue un payload différent = refus (anti-replay).';

-- -----------------------------------------------------------------------------
-- 11. integrations
-- -----------------------------------------------------------------------------
create table if not exists public.integrations (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid not null,
    provider          text not null,
    status            text not null default 'disconnected',
    scopes            text[] not null default '{}'::text[],
    secret_reference  text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint integrations_status_check check (status in ('connected', 'disconnected', 'error', 'revoked')),
    constraint integrations_user_provider_uniq unique (user_id, provider)
);

comment on column public.integrations.secret_reference is 'Référence vers le gestionnaire de secrets ; JAMAIS le secret lui-même.';

-- -----------------------------------------------------------------------------
-- 12. audit_logs (append-only côté client)
-- -----------------------------------------------------------------------------
create table if not exists public.audit_logs (
    id                 uuid primary key default gen_random_uuid(),
    user_id            uuid,
    actor_type         text not null default 'user',
    actor_id           text,
    action             text not null,
    resource_type      text,
    resource_id        text,
    decision           text not null default 'allow',
    metadata_redacted  jsonb not null default '{}'::jsonb,
    created_at         timestamptz not null default now(),
    constraint audit_logs_actor_type_check check (actor_type in ('user', 'system', 'worker', 'skill', 'integration', 'agent', 'api')),
    constraint audit_logs_decision_check check (decision in ('allow', 'deny', 'require_approval', 'error'))
);

comment on table public.audit_logs is 'Journal d''audit des décisions d''autorisation. Écrit par le backend (service_role), lecture seule pour l''utilisateur.';

-- -----------------------------------------------------------------------------
-- 13. notifications
-- -----------------------------------------------------------------------------
create table if not exists public.notifications (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null,
    type           text not null,
    title          text not null,
    body           text,
    read_at        timestamptz,
    resource_type  text,
    resource_id    text,
    created_at     timestamptz not null default now(),
    constraint notifications_title_len check (char_length(title) between 1 and 200)
);

-- -----------------------------------------------------------------------------
-- FK conditionnel vers auth.users (Supabase fournit le schéma `auth`).
-- Sur un PostgreSQL nu, la contrainte est simplement omise : la colonne
-- profiles.id reste la clé d'identité fournie par l'application.
-- -----------------------------------------------------------------------------
do $do$
begin
    if exists (
        select 1 from pg_tables where schemaname = 'auth' and tablename = 'users'
    ) and not exists (
        select 1 from pg_constraint where conname = 'profiles_id_fkey'
    ) then
        alter table public.profiles
            add constraint profiles_id_fkey
            foreign key (id) references auth.users (id) on delete cascade;
        raise notice 'profiles_id_fkey -> auth.users : ajoutée';
    else
        raise notice 'profiles_id_fkey -> auth.users : ignorée (schéma auth absent ou contrainte déjà présente)';
    end if;
end
$do$;

-- -----------------------------------------------------------------------------
-- Index (docs/06-data/DATA_MODEL.md §5)
-- -----------------------------------------------------------------------------
-- user_id
create index if not exists idx_conversations_user_id   on public.conversations (user_id);
create index if not exists idx_messages_user_id        on public.messages (user_id);
create index if not exists idx_tasks_user_id           on public.tasks (user_id);
create index if not exists idx_memories_user_id        on public.memories (user_id);
create index if not exists idx_approvals_user_id       on public.approvals (user_id);
create index if not exists idx_integrations_user_id    on public.integrations (user_id);
create index if not exists idx_notifications_user_id   on public.notifications (user_id);
create index if not exists idx_audit_logs_user_id      on public.audit_logs (user_id);

-- conversation_id
create index if not exists idx_messages_conversation_id on public.messages (conversation_id, created_at);
create index if not exists idx_tasks_conversation_id    on public.tasks (conversation_id);

-- task_id
create index if not exists idx_task_steps_task_id  on public.task_steps (task_id);
create index if not exists idx_executions_task_id  on public.executions (task_id);
create index if not exists idx_executions_step_id  on public.executions (step_id);
create index if not exists idx_approvals_task_id   on public.approvals (task_id);

-- status
create index if not exists idx_tasks_status        on public.tasks (status);
create index if not exists idx_task_steps_status   on public.task_steps (status);
create index if not exists idx_executions_status   on public.executions (status);
create index if not exists idx_approvals_status    on public.approvals (status);
create index if not exists idx_skill_versions_status on public.skill_versions (status);

-- created_at (lecture chronologique inverse)
create index if not exists idx_conversations_created_at on public.conversations (created_at desc);
create index if not exists idx_tasks_created_at         on public.tasks (created_at desc);
create index if not exists idx_notifications_created_at on public.notifications (created_at desc);
create index if not exists idx_audit_logs_created_at    on public.audit_logs (created_at desc);

-- divers
create index if not exists idx_notifications_unread
    on public.notifications (user_id, created_at desc) where read_at is null;
create index if not exists idx_approvals_pending
    on public.approvals (user_id, expires_at) where status = 'pending';
create index if not exists idx_task_steps_depends_on
    on public.task_steps using gin (depends_on);
create index if not exists idx_memories_category
    on public.memories (user_id, category);
create index if not exists idx_memories_expires_at
    on public.memories (expires_at) where expires_at is not null;

-- idempotence des exécutions : unique seulement quand la clé est fournie
create unique index if not exists uq_executions_idempotency_key
    on public.executions (idempotency_key) where idempotency_key is not null;

-- une seule version active par skill
create unique index if not exists uq_skill_versions_one_active
    on public.skill_versions (skill_id) where status = 'active';

-- pgvector : recherche sémantique cosinus sur les mémoires indexées
create index if not exists idx_memories_embedding
    on public.memories using hnsw (embedding vector_cosine_ops)
    where embedding is not null;

-- -----------------------------------------------------------------------------
-- Triggers updated_at
-- -----------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $fn$
begin
    new.updated_at := now();
    return new;
end;
$fn$;

do $do$
declare
    t text;
begin
    foreach t in array array[
        'profiles', 'conversations', 'tasks', 'task_steps', 'memories', 'integrations'
    ]
    loop
        execute format('drop trigger if exists trg_%1$s_updated_at on public.%1$s', t);
        execute format(
            'create trigger trg_%1$s_updated_at before update on public.%1$s '
            'for each row execute function public.set_updated_at()', t);
    end loop;
end
$do$;

-- -----------------------------------------------------------------------------
-- handle_new_user : profil créé automatiquement à l'inscription Supabase
-- -----------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $fn$
begin
    insert into public.profiles (id, display_name, locale)
    values (
        new.id,
        coalesce(
            nullif(new.raw_user_meta_data ->> 'display_name', ''),
            nullif(split_part(coalesce(new.email, ''), '@', 1), ''),
            'Utilisateur'
        ),
        coalesce(nullif(new.raw_user_meta_data ->> 'locale', ''), 'fr')
    )
    on conflict (id) do nothing;
    return new;
end;
$fn$;

do $do$
begin
    if exists (select 1 from pg_tables where schemaname = 'auth' and tablename = 'users') then
        execute 'drop trigger if exists on_auth_user_created on auth.users';
        execute 'create trigger on_auth_user_created after insert on auth.users '
                'for each row execute function public.handle_new_user()';
        raise notice 'trigger on_auth_user_created : créé sur auth.users';
    else
        raise notice 'trigger on_auth_user_created : ignoré (schéma auth absent)';
    end if;
end
$do$;

commit;

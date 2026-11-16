-- =============================================================================
-- Kwes — 0000_local_auth_shim.sql  (LOCAL / CI UNIQUEMENT)
--
-- ⚠️  Ne JAMAIS appliquer sur un projet Supabase : Supabase fournit déjà
--     `auth.users`, `auth.uid()`, `auth.role()` et les rôles `anon` /
--     `authenticated` avec les bons privilèges. Ce fichier existe seulement
--     pour rejouer les migrations sur un PostgreSQL nu (Docker) et prouver que
--     le schéma + la RLS sont valides hors plateforme.
--
-- Émule le strict nécessaire :
--   * schéma `auth` + table `auth.users` (id, email, raw_user_meta_data) ;
--   * `auth.uid()` : lit `request.jwt.claim.sub` (posé par PostgREST) ou
--     `request.jwt.claims` (JSON), comme le fait Supabase ;
--   * `auth.role()` ;
--   * rôles `anon`, `authenticated`, `service_role` (NOLOGIN).
--
-- Usage :
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/local/0000_local_auth_shim.sql
-- =============================================================================

begin;

create schema if not exists auth;
create schema if not exists extensions;

create extension if not exists pgcrypto;

create table if not exists auth.users (
    id                 uuid primary key default gen_random_uuid(),
    email              text unique,
    encrypted_password text,
    raw_user_meta_data jsonb not null default '{}'::jsonb,
    created_at         timestamptz not null default now()
);

-- Rôles Supabase (idempotent)
do $do$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin noinherit;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin noinherit;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin noinherit bypassrls;
    end if;
end
$do$;

-- auth.uid() : équivalent Supabase (claim `sub` du JWT)
create or replace function auth.uid()
returns uuid
language sql
stable
as $fn$
    select coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'
    )::uuid;
$fn$;

-- auth.role() : claim `role` ('authenticated', 'anon', 'service_role')
create or replace function auth.role()
returns text
language sql
stable
as $fn$
    select coalesce(
        nullif(current_setting('request.jwt.claim.role', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
        'anon'
    );
$fn$;

-- auth.jwt() : payload complet, utile aux policies avancées
create or replace function auth.jwt()
returns jsonb
language sql
stable
as $fn$
    select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$fn$;

grant usage on schema auth to anon, authenticated, service_role;
grant usage on schema public to anon, authenticated, service_role;
grant select on auth.users to service_role;

commit;

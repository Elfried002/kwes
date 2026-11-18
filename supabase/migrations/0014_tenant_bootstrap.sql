-- 0014_tenant_bootstrap.sql — création d'espaces de travail sous RLS
--
-- Problème : avec la RLS réellement active (rôle kwes_app), un utilisateur ne
-- peut pas insérer un tenant puis son appartenance, puisque la politique
-- d'insertion exige déjà d'être membre. Résultat : la première connexion échoue.
--
-- Solution : deux fonctions SECURITY DEFINER, appelées par l'application, qui
-- créent l'espace et l'appartenance de façon atomique et idempotente, en
-- vérifiant toujours auth.uid(). Aucune insertion directe n'est ouverte.

begin;

-- Espace personnel : l'identifiant du tenant est celui du profil.
create or replace function public.kwes_ensure_personal_tenant()
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    uid uuid := auth.uid();
    tname text;
begin
    if uid is null then
        raise exception 'utilisateur non authentifié' using errcode = '28000';
    end if;

    if exists (select 1 from tenants where id = uid) then
        return uid;
    end if;

    select coalesce(nullif(btrim(display_name), ''), 'Mon espace')
      into tname
      from profiles where id = uid;

    insert into tenants (id, name, slug, plan, created_at, updated_at)
    values (uid, coalesce(tname, 'Mon espace'), 'perso-' || left(uid::text, 8), 'free', now(), now())
    on conflict (id) do nothing;

    insert into tenant_memberships (id, tenant_id, user_id, role, created_at)
    values (gen_random_uuid(), uid, uid, 'owner', now())
    on conflict (tenant_id, user_id) do nothing;

    insert into tenant_settings (tenant_id, locale, timezone, voice_language, data, updated_at)
    values (uid, 'fr', 'Africa/Abidjan', 'fr', '{}'::jsonb, now())
    on conflict (tenant_id) do nothing;

    return uid;
end;
$$;

-- Espace d'équipe : créé par un utilisateur authentifié, qui en devient owner.
create or replace function public.kwes_create_tenant(p_name text)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    uid uuid := auth.uid();
    new_id uuid := gen_random_uuid();
    clean text := btrim(coalesce(p_name, ''));
begin
    if uid is null then
        raise exception 'utilisateur non authentifié' using errcode = '28000';
    end if;
    if length(clean) < 2 then
        raise exception 'nom d''espace trop court' using errcode = '22023';
    end if;

    insert into tenants (id, name, slug, plan, created_at, updated_at)
    values (new_id, left(clean, 120), 'team-' || left(new_id::text, 8), 'free', now(), now());

    insert into tenant_memberships (id, tenant_id, user_id, role, created_at)
    values (gen_random_uuid(), new_id, uid, 'owner', now());

    insert into tenant_settings (tenant_id, locale, timezone, voice_language, data, updated_at)
    values (new_id, 'fr', 'Africa/Abidjan', 'fr', '{}'::jsonb, now())
    on conflict (tenant_id) do nothing;

    return new_id;
end;
$$;

grant execute on function public.kwes_ensure_personal_tenant() to authenticated, kwes_app;
grant execute on function public.kwes_create_tenant(text) to authenticated, kwes_app;

commit;

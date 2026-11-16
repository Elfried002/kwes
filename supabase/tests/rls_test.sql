-- =============================================================================
-- Kwes — supabase/tests/rls_test.sql
-- Test fonctionnel d'isolation RLS (pas seulement « RLS est activée »).
--
-- À exécuter APRÈS 0000 (shim local) + 0001 + 0002 + 0003, en superutilisateur :
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/tests/rls_test.sql
--
-- Chaque assertion lève une exception si elle échoue => code retour non nul.
-- Le script est idempotent (fixtures en ON CONFLICT DO NOTHING) et se termine
-- par un ROLLBACK : aucune donnée de test ne persiste (sauf si --keep).
-- =============================================================================

\set ON_ERROR_STOP on
\set alice '''aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1'''
\set bob   '''bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'''

begin;

\echo '--- Fixtures (rôle propriétaire, bypass RLS) ---'

insert into auth.users (id, email, raw_user_meta_data)
values (:alice, 'alice@kwes.test', '{"display_name":"Alice","locale":"fr"}'),
       (:bob,   'bob@kwes.test',   '{"display_name":"Bob","locale":"en"}')
on conflict (id) do nothing;

-- handle_new_user doit avoir créé les profils
do $$
declare n int;
begin
    select count(*) into n from public.profiles
     where id in ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
                  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1');
    if n <> 2 then
        raise exception 'ÉCHEC handle_new_user : % profils créés au lieu de 2', n;
    end if;
    raise notice 'OK  handle_new_user : 2 profils auto-créés';
end $$;

insert into public.conversations (id, user_id, title)
values ('c0000000-0000-4000-8000-00000000000a',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 'Conversation d''Alice')
on conflict (id) do nothing;

insert into public.messages (id, conversation_id, user_id, role, content)
values ('d0000000-0000-4000-8000-00000000000a',
        'c0000000-0000-4000-8000-00000000000a',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 'user', 'Bonjour, je suis Alice')
on conflict (id) do nothing;

insert into public.tasks (id, user_id, conversation_id, title, status)
values ('e0000000-0000-4000-8000-00000000000a',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1',
        'c0000000-0000-4000-8000-00000000000a', 'Mission d''Alice', 'running')
on conflict (id) do nothing;

insert into public.task_steps (id, task_id, step_key, title, status)
values ('f0000000-0000-4000-8000-00000000000a',
        'e0000000-0000-4000-8000-00000000000a', 'collect', 'Collecte', 'running')
on conflict (id) do nothing;

insert into public.memories (id, user_id, content, sensitivity)
values ('a0000000-0000-4000-8000-00000000000a',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 'Alice préfère le français', 'private')
on conflict (id) do nothing;

\echo ''
\echo '--- 1. Alice (authenticated) ne voit que ses données ---'

set local role authenticated;
set local request.jwt.claims = '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1","role":"authenticated"}';

do $$
declare
    n int;
begin
    select count(*) into n from public.conversations;
    if n <> 1 then raise exception 'ÉCHEC: Alice voit % conversations (attendu 1)', n; end if;

    select count(*) into n from public.messages;
    if n <> 1 then raise exception 'ÉCHEC: Alice voit % messages (attendu 1)', n; end if;

    select count(*) into n from public.tasks;
    if n <> 1 then raise exception 'ÉCHEC: Alice voit % tasks (attendu 1)', n; end if;

    select count(*) into n from public.task_steps;
    if n <> 1 then raise exception 'ÉCHEC: Alice voit % task_steps (attendu 1)', n; end if;

    select count(*) into n from public.memories;
    if n <> 1 then raise exception 'ÉCHEC: Alice voit % memories (attendu 1)', n; end if;

    select count(*) into n from public.profiles;
    if n <> 1 then raise exception 'ÉCHEC: Alice voit % profils (attendu 1)', n; end if;

    raise notice 'OK  Alice voit exactement ses 6 lignes (conv, msg, task, step, memory, profil)';
end $$;

\echo ''
\echo '--- 2. Bob ne voit RIEN des données d''Alice ---'

set local request.jwt.claims = '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1","role":"authenticated"}';

do $$
declare
    n int;
begin
    select count(*) into n from public.conversations;
    if n <> 0 then raise exception 'ÉCHEC: Bob voit % conversations d''Alice', n; end if;

    select count(*) into n from public.messages;
    if n <> 0 then raise exception 'ÉCHEC: Bob voit % messages d''Alice', n; end if;

    select count(*) into n from public.tasks;
    if n <> 0 then raise exception 'ÉCHEC: Bob voit % tasks d''Alice', n; end if;

    select count(*) into n from public.task_steps;
    if n <> 0 then raise exception 'ÉCHEC: Bob voit % task_steps d''Alice', n; end if;

    select count(*) into n from public.memories;
    if n <> 0 then raise exception 'ÉCHEC: Bob voit % memories d''Alice', n; end if;

    select count(*) into n from public.executions;
    if n <> 0 then raise exception 'ÉCHEC: Bob voit % executions', n; end if;

    -- Les skills sont un référentiel partagé : lecture autorisée
    select count(*) into n from public.skills;
    if n <> 3 then raise exception 'ÉCHEC: Bob voit % skills (attendu 3, référentiel partagé)', n; end if;

    raise notice 'OK  Bob ne voit aucune ligne privée d''Alice ; les 3 skills restent lisibles';
end $$;

\echo ''
\echo '--- 3. Écritures inter-utilisateur refusées ---'

do $$
begin
    begin
        insert into public.memories (user_id, content)
        values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 'injection de Bob');
        raise exception 'ÉCHEC: Bob a pu écrire une mémoire au nom d''Alice';
    exception when insufficient_privilege then
        raise notice 'OK  insert memories(user_id=Alice) par Bob refusé par la RLS';
    end;

    begin
        insert into public.conversations (user_id, title)
        values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1', 'conversation forgée');
        raise exception 'ÉCHEC: Bob a pu créer une conversation au nom d''Alice';
    exception when insufficient_privilege then
        raise notice 'OK  insert conversations(user_id=Alice) par Bob refusé par la RLS';
    end;

    begin
        insert into public.tasks (user_id, conversation_id, title)
        values ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1',
                'c0000000-0000-4000-8000-00000000000a', 'task dans la conv d''Alice');
        raise exception 'ÉCHEC: Bob a pu créer une task dans la conversation d''Alice';
    exception when insufficient_privilege then
        raise notice 'OK  task rattachée à la conversation d''Alice refusée';
    end;

    begin
        insert into public.executions (task_id, tool_name, status)
        values ('e0000000-0000-4000-8000-00000000000a', 'web.search', 'running');
        raise exception 'ÉCHEC: Bob a pu écrire une execution sur la task d''Alice';
    exception when insufficient_privilege then
        raise notice 'OK  insert executions refusé (table en lecture seule côté client)';
    end;

    begin
        insert into public.audit_logs (user_id, action, decision)
        values ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1', 'forged', 'allow');
        raise exception 'ÉCHEC: un client a pu écrire dans audit_logs';
    exception when insufficient_privilege then
        raise notice 'OK  insert audit_logs refusé (journal serveur uniquement)';
    end;

    begin
        insert into public.skills (name, description)
        values ('malicious_skill', 'skill injecté par un client');
        raise exception 'ÉCHEC: un client a pu créer un skill';
    exception when insufficient_privilege then
        raise notice 'OK  insert skills refusé (référentiel en lecture seule)';
    end;
end $$;

\echo ''
\echo '--- 4. Mises à jour / suppressions inter-utilisateur sans effet ---'

do $$
declare
    n int;
begin
    update public.conversations set title = 'piratée' where id = 'c0000000-0000-4000-8000-00000000000a';
    get diagnostics n = row_count;
    if n <> 0 then raise exception 'ÉCHEC: Bob a modifié % conversation(s) d''Alice', n; end if;

    delete from public.memories where id = 'a0000000-0000-4000-8000-00000000000a';
    get diagnostics n = row_count;
    if n <> 0 then raise exception 'ÉCHEC: Bob a supprimé % mémoire(s) d''Alice', n; end if;

    raise notice 'OK  update/delete inter-utilisateur : 0 ligne affectée';
end $$;

\echo ''
\echo '--- 5. anon n''a aucun accès ---'

reset role;
set local role anon;

do $$
begin
    begin
        perform 1 from public.conversations limit 1;
        raise exception 'ÉCHEC: anon peut lire public.conversations';
    exception when insufficient_privilege then
        raise notice 'OK  anon refusé sur conversations (permission denied)';
    end;

    begin
        perform 1 from public.memories limit 1;
        raise exception 'ÉCHEC: anon peut lire public.memories';
    exception when insufficient_privilege then
        raise notice 'OK  anon refusé sur memories (permission denied)';
    end;
end $$;

\echo ''
\echo '--- 6. Sans JWT, authenticated ne voit rien (pas de fuite par défaut) ---'

reset role;
set local role authenticated;
set local request.jwt.claims = '{}';

do $$
declare n int;
begin
    select count(*) into n from public.conversations;
    if n <> 0 then raise exception 'ÉCHEC: sans claim sub, % lignes visibles', n; end if;
    raise notice 'OK  sans claim sub : 0 ligne visible (auth.uid() NULL)';
end $$;

reset role;

rollback;

\echo ''
\echo '=== RLS : toutes les assertions sont passées ==='

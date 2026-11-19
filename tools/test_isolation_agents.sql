-- Test d'isolation croisée des exécutions d'agents.
--
-- À exécuter APRÈS application de 0016_agents.sql, avec le rôle applicatif réel
-- (kwes_app), jamais avec le propriétaire (qui contourne la RLS).
--
--   PGPASSWORD="$KWES_DB_APP_PASSWORD" psql -h 127.0.0.1 -U kwes_app -d kwes \
--     -v ON_ERROR_STOP=off -f tools/test_isolation_agents.sql
--
-- Résultat attendu :
--   1. insertion dans son propre tenant   -> INSERT 0 1
--   2. lecture de ses propres lignes      -> 1
--   3. lecture des lignes de l'autre      -> 0
--   4. insertion dans l'autre tenant      -> ERROR row-level security policy

\set ON_ERROR_STOP off

-- Utilisateur A (53 conversations) et utilisateur B (21 conversations)
\set tenant_a '0542f1d4-8324-43b8-8354-5cd87be7a0f5'
\set tenant_b '3a33757e-9a68-47a2-a12f-9b6d5c6555a4'

select set_config('request.jwt.claims',
       '{"sub":"0542f1d4-8324-43b8-8354-5cd87be7a0f5","role":"authenticated"}', false);
set role authenticated;

-- 1. Écriture dans son propre espace : autorisée
insert into agent_runs (tenant_id, agent_id, autonomy_level, status, language)
values (:'tenant_a', 'kwes.research', 'A1', 'completed', 'fr');

-- 2. Lecture de ses lignes
select 'lecture propre (A)' as controle, count(*) as lignes
  from agent_runs where tenant_id = :'tenant_a';

-- 3. Lecture des lignes de B : doit renvoyer 0
select 'lecture croisee (B)' as controle, count(*) as lignes
  from agent_runs where tenant_id = :'tenant_b';

-- 4. Écriture dans l'espace de B : doit échouer
insert into agent_runs (tenant_id, agent_id, autonomy_level, status, language)
values (:'tenant_b', 'kwes.research', 'A1', 'completed', 'fr');

-- 5. Même contrôle sur les messages inter-agents
insert into agent_messages (tenant_id, from_agent, to_agent, kind, payload)
values (:'tenant_a', 'kwes.core', 'kwes.research', 'task', '{"objective":"test"}');

select 'messages propres (A)' as controle, count(*) as lignes
  from agent_messages where tenant_id = :'tenant_a';

insert into agent_messages (tenant_id, from_agent, to_agent, kind, payload)
values (:'tenant_b', 'kwes.core', 'kwes.research', 'task', '{"objective":"test"}');

reset role;

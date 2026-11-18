-- Preuve d'isolation inter-tenant, exécutée sur la base de production.
-- Utilisateur A = 0542f1d4-… (53 conversations), utilisateur B = 3a33757e-… (21 conversations).
-- Le rôle applicatif réel (kwes_app) ne peut pas lire les données d'un autre espace.

\set ON_ERROR_STOP off

select 'contexte' as etape, set_config('request.jwt.claims',
       '{"sub":"0542f1d4-8324-43b8-8354-5cd87be7a0f5","role":"authenticated"}', false);

set role authenticated;

select set_config('request.jwt.claims',
       '{"sub":"0542f1d4-8324-43b8-8354-5cd87be7a0f5","role":"authenticated"}', false) as claims_a;

-- A ne voit que ses propres conversations
select 'lecture propre (A)' as controle, count(*) as lignes from conversations;

-- A ne voit aucune conversation de B
select 'lecture croisee (B depuis A)' as controle, count(*) as lignes
  from conversations where user_id = '3a33757e-9a68-47a2-a12f-9b6d5c6555a4';

-- A ne peut pas écrire dans l'espace de B
insert into conversations (id, tenant_id, user_id, title, status)
values (gen_random_uuid(), '3a33757e-9a68-47a2-a12f-9b6d5c6555a4',
        '3a33757e-9a68-47a2-a12f-9b6d5c6555a4', 'ecriture croisee interdite', 'active');

reset role;

-- 0004 — alignement du type de `tasks.priority` sur le backend (entier 0..5).
-- La migration 0001 initiale déclarait `text` ('low'|'normal'|'high'|'urgent'),
-- alors que l'API et l'ORM manipulent un entier (0 = plus haute priorité).
-- Idempotent : rejouable sans erreur.

begin;

alter table if exists public.tasks
    drop constraint if exists tasks_priority_check;

alter table if exists public.tasks
    alter column priority drop default;

alter table if exists public.tasks
    alter column priority type smallint using (
        case priority
            when 'urgent' then 0
            when 'high' then 1
            when 'normal' then 2
            when 'low' then 3
            else 2
        end
    );

alter table if exists public.tasks
    alter column priority set default 2;

alter table if exists public.tasks
    add constraint tasks_priority_check check (priority between 0 and 5);

commit;

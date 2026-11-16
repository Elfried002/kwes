-- 0004 — alignement du type de `tasks.priority` sur le backend (entier 0..5).
-- La version initiale de 0001 déclarait `text` ('low'|'normal'|'high'|'urgent'),
-- alors que l'API et l'ORM manipulent un entier (0 = plus haute priorité).
--
-- La 0001 actuelle déclare déjà `smallint` : cette migration ne convertit donc
-- que les bases créées avec l'ancienne définition. Idempotente et sans effet
-- sur une base neuve.

do $do$
declare
    current_type text;
begin
    select data_type into current_type
    from information_schema.columns
    where table_schema = 'public' and table_name = 'tasks' and column_name = 'priority';

    if current_type is null then
        return;  -- table absente : rien à faire
    end if;

    if current_type = 'text' then
        alter table public.tasks drop constraint if exists tasks_priority_check;
        alter table public.tasks alter column priority drop default;
        alter table public.tasks
            alter column priority type smallint using (
                case priority
                    when 'urgent' then 0
                    when 'high' then 1
                    when 'normal' then 2
                    when 'low' then 3
                    else 2
                end
            );
        alter table public.tasks alter column priority set default 2;
        alter table public.tasks
            add constraint tasks_priority_check check (priority between 0 and 5);
    end if;
end
$do$;

-- 0009 — Aligne les contraintes de `memories` sur le vocabulaire réellement
-- utilisé par l'application (API /memory, skill remember, tests).
--
-- Constat du 16/11 : la migration 0001 imposait category ∈ (fact, preference,
-- goal, constraint, project, relationship, other) et sensitivity ∈ (public,
-- internal, private, restricted), alors que le code applicatif valide
-- working/episodic/semantic/procedural et normal/personal/sensitive. Aucune
-- écriture de mémoire n'existait encore, d'où l'incohérence jamais détectée.
-- Les valeurs héritées sont converties avant le remplacement des contraintes.

begin;

update public.memories
set category = case category
    when 'working' then 'working'
    when 'episodic' then 'episodic'
    when 'semantic' then 'semantic'
    when 'procedural' then 'procedural'
    when 'project' then 'working'
    when 'relationship' then 'episodic'
    when 'fact' then 'semantic'
    when 'preference' then 'semantic'
    when 'goal' then 'semantic'
    when 'constraint' then 'semantic'
    else 'semantic'
end
where category is null
   or category not in ('working', 'episodic', 'semantic', 'procedural');

update public.memories
set sensitivity = case sensitivity
    when 'normal' then 'normal'
    when 'personal' then 'personal'
    when 'sensitive' then 'sensitive'
    when 'public' then 'normal'
    when 'internal' then 'personal'
    when 'private' then 'personal'
    when 'restricted' then 'sensitive'
    else 'normal'
end
where sensitivity is null
   or sensitivity not in ('normal', 'personal', 'sensitive');

alter table public.memories drop constraint if exists memories_category_check;
alter table public.memories add constraint memories_category_check
    check (category in ('working', 'episodic', 'semantic', 'procedural'));

alter table public.memories drop constraint if exists memories_sensitivity_check;
alter table public.memories add constraint memories_sensitivity_check
    check (sensitivity in ('normal', 'personal', 'sensitive'));

alter table public.memories alter column category set default 'semantic';
alter table public.memories alter column sensitivity set default 'normal';

commit;

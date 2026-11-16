-- P0 : verrou d'exécution explicite sur les tâches.
-- Non destructif : deux colonnes nullables + un index.
-- Le worker revendique une tâche avant de l'exécuter (UPDATE ... WHERE claimed_by IS NULL)
-- et libère le verrou à la fin. Un verrou plus vieux que le TTL est considéré comme abandonné.

alter table public.tasks
    add column if not exists claimed_by text,
    add column if not exists claimed_at timestamptz;

create index if not exists tasks_claimed_by_idx on public.tasks (claimed_by);

comment on column public.tasks.claimed_by is
    'Identifiant du worker qui détient le verrou d''exécution (P0).';
comment on column public.tasks.claimed_at is
    'Horodatage de la prise du verrou ; au-delà du TTL, le verrou est réputé abandonné.';

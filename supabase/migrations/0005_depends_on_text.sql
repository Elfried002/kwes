-- 0005 — `task_steps.depends_on` doit contenir des clés d'étape (text),
-- pas des UUID : l'ORM et le planner manipulent des `step_key` ('step_1').
-- Idempotent.

begin;

alter table if exists public.task_steps
    drop constraint if exists task_steps_depends_on_fkey;

drop index if exists public.idx_task_steps_depends_on;

alter table if exists public.task_steps
    alter column depends_on drop default;

alter table if exists public.task_steps
    alter column depends_on type text[] using (depends_on::text[]);

alter table if exists public.task_steps
    alter column depends_on set default '{}'::text[];

create index if not exists idx_task_steps_depends_on on public.task_steps using gin (depends_on);

commit;

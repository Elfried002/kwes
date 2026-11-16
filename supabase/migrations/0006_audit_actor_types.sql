-- 0006 — autoriser les acteurs réellement émis par le backend.
-- L'orchestrateur journalise `agent` ; l'énumération initiale ne prévoyait que
-- user / system / worker / skill / integration.
-- Idempotent.

begin;

alter table if exists public.audit_logs
    drop constraint if exists audit_logs_actor_type_check;

alter table if exists public.audit_logs
    add constraint audit_logs_actor_type_check
    check (actor_type in ('user', 'system', 'worker', 'skill', 'integration', 'agent', 'api'));

commit;

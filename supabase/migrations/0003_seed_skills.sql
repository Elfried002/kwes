-- =============================================================================
-- Kwes — 0003_seed_skills.sql
-- Seed des 3 skills Alpha (docs/09-skills/SKILL_SPECIFICATION.md §5) en version
-- active. Idempotent : réexécutable sans doublon de skill ni de version.
--
-- Les skills sont insérés par `name` (clé métier) puis les versions sont
-- rattachées par SELECT sur ce nom : le seed reste correct même si un skill
-- existe déjà avec un id différent (créé par l'application ou en démo).
-- Les UUID de version sont fixes et réservés (plage 2222...) pour que dev, CI
-- et démo partagent les mêmes identifiants.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- 1. Référentiel des skills
-- -----------------------------------------------------------------------------
insert into public.skills (name, description, current_version, enabled)
values
    ('web_research',
     'Recherche et synthèse de sources web accessibles, avec citations.',
     '1.0.0', true),
    ('business_planning',
     'Structuration d''un plan d''affaires : étapes, dépendances, risques, KPI.',
     '1.0.0', true),
    ('browser_readonly',
     'Lecture d''une page sur un domaine autorisé : titre, contenu, liens.',
     '1.0.0', true)
on conflict (name) do update
    set description     = excluded.description,
        current_version = excluded.current_version,
        enabled         = excluded.enabled;

-- -----------------------------------------------------------------------------
-- 2. Versions actives (manifestes conformes au §3 de la spécification)
-- -----------------------------------------------------------------------------
insert into public.skill_versions
    (id, skill_id, version, status, manifest_json, artifact_hash, approved_at)
select
    '22222222-2222-2222-2222-222222222201'::uuid,
    s.id,
    '1.0.0',
    'active',
    jsonb_build_object(
        'name', 'web_research',
        'version', '1.0.0',
        'description', 'Recherche et synthèse de sources web accessibles',
        'entrypoint', 'skill.py',
        'permissions', jsonb_build_array('web.search', 'web.read'),
        'risk_level', 'R0',
        'network', jsonb_build_object('mode', 'allowlist', 'domains', jsonb_build_array()),
        'resources', jsonb_build_object('timeout_seconds', 180, 'memory_mb', 512, 'cpu_limit', 1),
        'approval', jsonb_build_object('required_for', jsonb_build_array('external_publish')),
        'input_schema', jsonb_build_object('query', 'string', 'scope', 'string?', 'depth', 'integer?'),
        'output_schema', jsonb_build_object('sources', 'array', 'facts', 'array', 'summary', 'string', 'limits', 'array')
    ),
    'seed:web_research:1.0.0',
    now()
from public.skills s
where s.name = 'web_research'
on conflict (skill_id, version) do update
    set manifest_json = excluded.manifest_json,
        artifact_hash = excluded.artifact_hash,
        status        = excluded.status,
        approved_at   = coalesce(public.skill_versions.approved_at, excluded.approved_at);

insert into public.skill_versions
    (id, skill_id, version, status, manifest_json, artifact_hash, approved_at)
select
    '22222222-2222-2222-2222-222222222202'::uuid,
    s.id,
    '1.0.0',
    'active',
    jsonb_build_object(
        'name', 'business_planning',
        'version', '1.0.0',
        'description', 'Structuration d''un plan d''affaires',
        'entrypoint', 'skill.py',
        'permissions', jsonb_build_array(),
        'risk_level', 'R0',
        'network', jsonb_build_object('mode', 'disabled', 'domains', jsonb_build_array()),
        'resources', jsonb_build_object('timeout_seconds', 120, 'memory_mb', 256, 'cpu_limit', 1),
        'approval', jsonb_build_object('required_for', jsonb_build_array()),
        'input_schema', jsonb_build_object('objective', 'string', 'context', 'string?', 'constraints', 'array?'),
        'output_schema', jsonb_build_object('steps', 'array', 'dependencies', 'array', 'risks', 'array', 'kpis', 'array')
    ),
    'seed:business_planning:1.0.0',
    now()
from public.skills s
where s.name = 'business_planning'
on conflict (skill_id, version) do update
    set manifest_json = excluded.manifest_json,
        artifact_hash = excluded.artifact_hash,
        status        = excluded.status,
        approved_at   = coalesce(public.skill_versions.approved_at, excluded.approved_at);

insert into public.skill_versions
    (id, skill_id, version, status, manifest_json, artifact_hash, approved_at)
select
    '22222222-2222-2222-2222-222222222203'::uuid,
    s.id,
    '1.0.0',
    'active',
    jsonb_build_object(
        'name', 'browser_readonly',
        'version', '1.0.0',
        'description', 'Lecture seule d''une page sur domaine autorisé',
        'entrypoint', 'skill.py',
        'permissions', jsonb_build_array('browser.read'),
        'risk_level', 'R0',
        'network', jsonb_build_object('mode', 'allowlist', 'domains', jsonb_build_array()),
        'resources', jsonb_build_object('timeout_seconds', 90, 'memory_mb', 768, 'cpu_limit', 1),
        'approval', jsonb_build_object('required_for', jsonb_build_array()),
        'input_schema', jsonb_build_object('url', 'string', 'objective', 'string'),
        'output_schema', jsonb_build_object('title', 'string', 'content', 'string', 'links', 'array')
    ),
    'seed:browser_readonly:1.0.0',
    now()
from public.skills s
where s.name = 'browser_readonly'
on conflict (skill_id, version) do update
    set manifest_json = excluded.manifest_json,
        artifact_hash = excluded.artifact_hash,
        status        = excluded.status,
        approved_at   = coalesce(public.skill_versions.approved_at, excluded.approved_at);

-- Cohérence : current_version pointe bien sur la version active
update public.skills s
   set current_version = '1.0.0'
 where s.name in ('web_research', 'business_planning', 'browser_readonly');

commit;

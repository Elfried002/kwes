-- 0015 — statut « consumed » des approbations
--
-- L'orchestrateur marque une approbation `consumed` dès qu'il l'utilise, mais la
-- contrainte d'origine n'autorisait que pending/approved/rejected/expired : toute
-- mission approuvée échouait au moment de consommer l'approbation
-- (CheckViolation approvals_status_check), avec une étape bloquée en « running ».

alter table approvals
    drop constraint if exists approvals_status_check;

alter table approvals
    add constraint approvals_status_check
    check (status in ('pending', 'approved', 'rejected', 'expired', 'consumed'));

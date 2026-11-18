import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import {
  activeTenantId,
  createTenant,
  listTenants,
  switchTenant,
  type TenantSummary,
} from '../lib/tenants';

const ROLE_LABEL: Record<string, string> = {
  owner: 'Propriétaire',
  admin: 'Administrateur',
  member: 'Membre',
  viewer: 'Lecture seule',
};

/**
 * Sélecteur d'espace de travail : un utilisateur peut appartenir à plusieurs
 * espaces (personnel, équipe). Le changement recharge l'interface, car toutes
 * les données affichées dépendent du tenant actif.
 */
export function TenantSwitcher({ compact = false }: { compact?: boolean }) {
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let alive = true;
    listTenants()
      .then((rows) => {
        if (alive) setTenants(rows);
      })
      .catch(() => {
        /* non bloquant : l'interface reste utilisable sans sélecteur */
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent): void => {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const activeId = activeTenantId();
  const active = tenants.find((t) => t.id === activeId) ?? tenants[0] ?? null;

  const onNew = useCallback(async () => {
    const name = window.prompt("Nom du nouvel espace de travail");
    if (!name || name.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createTenant(name.trim());
      switchTenant(created.id);
    } catch {
      setError("Impossible de créer l'espace.");
      setBusy(false);
    }
  }, []);

  if (!active) return null;

  return (
    <div className="tenant-switch" ref={panelRef}>
      <button
        type="button"
        className={`tenant-switch__button${compact ? ' tenant-switch__button--compact' : ''}`}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Espace de travail : ${active.name}`}
      >
        <span className="tenant-switch__mark" aria-hidden="true">
          {active.name.slice(0, 1).toUpperCase()}
        </span>
        <span className="tenant-switch__text">
          <span className="tenant-switch__name">{active.name}</span>
          <span className="tenant-switch__role">{ROLE_LABEL[active.role] ?? active.role}</span>
        </span>
        <Icon name="chevron" size={14} />
      </button>

      {open ? (
        <div className="tenant-switch__menu" role="menu">
          {tenants.map((tenant) => (
            <button
              key={tenant.id}
              type="button"
              role="menuitem"
              className={`tenant-switch__item${tenant.id === active.id ? ' is-active' : ''}`}
              onClick={() => {
                if (tenant.id !== active.id) switchTenant(tenant.id);
                setOpen(false);
              }}
            >
              <span className="tenant-switch__item-name">{tenant.name}</span>
              <span className="tenant-switch__item-meta">
                {ROLE_LABEL[tenant.role] ?? tenant.role}
                {tenant.members ? ` · ${tenant.members} membre${tenant.members > 1 ? 's' : ''}` : ''}
              </span>
            </button>
          ))}
          <button type="button" className="tenant-switch__new" onClick={() => void onNew()} disabled={busy}>
            <Icon name="plus" size={14} />
            Nouvel espace
          </button>
          {error ? <p className="tenant-switch__error">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

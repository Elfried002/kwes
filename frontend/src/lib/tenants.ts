/**
 * Espaces de travail (tenants) côté client.
 *
 * L'espace actif est mémorisé localement et envoyé à l'API via `X-Tenant-Id`.
 * Le serveur ne fait jamais confiance à cet en-tête : il vérifie l'appartenance
 * réelle avant d'accepter le tenant.
 */

import { apiRequest } from './api';

const STORAGE_KEY = 'kwes.tenant.v1';

export interface TenantSummary {
  id: string;
  name: string;
  slug: string | null;
  plan: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  is_personal: boolean;
  members: number | null;
}

export interface TenantMember {
  id: string;
  user_id: string;
  role: string;
  created_at: string | null;
  display_name: string | null;
  is_you: boolean;
}

export function activeTenantId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setActiveTenant(id: string | null): void {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* stockage indisponible : on reste sur l'espace par défaut du serveur */
  }
}

export async function listTenants(): Promise<TenantSummary[]> {
  return apiRequest<TenantSummary[]>('/tenants');
}

export async function createTenant(name: string): Promise<TenantSummary> {
  return apiRequest<TenantSummary>('/tenants', { method: 'POST', body: { name } });
}

export async function listMembers(tenantId: string): Promise<TenantMember[]> {
  return apiRequest<TenantMember[]>(`/tenants/${tenantId}/members`);
}

export interface CurrentTenant {
  id: string;
  name: string;
  slug: string | null;
  role: string;
  is_personal: boolean;
  can_write: boolean;
  can_manage: boolean;
  settings: { locale: string; timezone: string; voice_language: string };
}

export async function currentTenant(): Promise<CurrentTenant> {
  return apiRequest<CurrentTenant>('/tenants/current');
}

/** Change d'espace et recharge l'interface (les données affichées changent toutes). */
export function switchTenant(id: string): void {
  setActiveTenant(id);
  window.location.reload();
}

import { useSyncExternalStore } from 'react';

/** Session côté navigateur : seul le JWT est stocké. Aucun secret n'est présent dans le bundle. */

const STORAGE_KEY = 'kwes.session.v1';

export interface Session {
  token: string;
  email: string;
  userId: string;
  expiresAt: number | null;
}

interface JwtClaims {
  sub?: string;
  email?: string;
  exp?: number;
  [key: string]: unknown;
}

function base64UrlDecode(segment: string): string {
  const padded = segment.replace(/-/g, '+').replace(/_/g, '/');
  const pad = padded.length % 4 === 0 ? '' : '='.repeat(4 - (padded.length % 4));
  const binary = atob(padded + pad);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export function decodeJwt(token: string): JwtClaims | null {
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    const payload = base64UrlDecode(parts[1] ?? '');
    const parsed: unknown = JSON.parse(payload);
    if (typeof parsed !== 'object' || parsed === null) return null;
    return parsed as JwtClaims;
  } catch {
    return null;
  }
}

export function sessionFromToken(token: string): { ok: true; session: Session } | { ok: false; error: string } {
  const trimmed = token.trim();
  if (!trimmed) return { ok: false, error: 'Le jeton est vide.' };
  const claims = decodeJwt(trimmed);
  if (!claims) return { ok: false, error: 'Ce jeton ne ressemble pas à un JWT (3 segments base64url).' };
  const exp = typeof claims.exp === 'number' ? claims.exp : null;
  if (exp !== null && exp * 1000 <= Date.now()) {
    return { ok: false, error: 'Ce jeton est expiré. Demande-en un nouveau.' };
  }
  return {
    ok: true,
    session: {
      token: trimmed,
      email: typeof claims.email === 'string' ? claims.email : '',
      userId: typeof claims.sub === 'string' ? claims.sub : '',
      expiresAt: exp,
    },
  };
}

let current: Session | null = readStored();
const listeners = new Set<() => void>();

function readStored(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return null;
    const candidate = parsed as Partial<Session>;
    if (typeof candidate.token !== 'string') return null;
    const result = sessionFromToken(candidate.token);
    if (!result.ok) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return result.session;
  } catch {
    return null;
  }
}

function emit(): void {
  for (const listener of listeners) listener();
}

export function getSession(): Session | null {
  return current;
}

export function getToken(): string | null {
  return current?.token ?? null;
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function saveSession(token: string): { ok: true; session: Session } | { ok: false; error: string } {
  const result = sessionFromToken(token);
  if (!result.ok) return result;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(result.session));
  } catch {
    // Stockage indisponible (navigation privée stricte) : session en mémoire seulement.
  }
  current = result.session;
  emit();
  return result;
}

export function clearSession(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  current = null;
  emit();
}

export function useSession(): Session | null {
  return useSyncExternalStore(subscribeSession, getSession, getSession);
}

if (typeof window !== 'undefined') {
  window.addEventListener('kwes:unauthorized', () => clearSession());
}

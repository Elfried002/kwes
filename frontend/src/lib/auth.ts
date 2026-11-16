import { useSyncExternalStore } from 'react';
import type { Session as SupabaseSession } from '@supabase/supabase-js';
import { supabase } from './supabase';

/**
 * Session côté navigateur, adossée à Supabase Auth.
 *
 * Supabase conserve lui-même les jetons (localStorage, clé `kwes.auth.supabase`) et
 * les rafraîchit automatiquement. Ce module expose une vue minimale et stable
 * ({ token, email, userId, expiresAt }) consommée par le reste de l'application :
 * `token` est toujours l'`access_token` Supabase présenté à l'API.
 */

const STORAGE_KEY = 'kwes.session.v1';
const LEGACY_DEV_TOKEN_KEY = 'kwes.dev.token.v1';

export interface Session {
  token: string;
  email: string;
  userId: string;
  expiresAt: number | null;
}

interface AuthState {
  session: Session | null;
  ready: boolean;
  recovery: boolean;
}

let state: AuthState = { session: readStored(), ready: false, recovery: false };
const listeners = new Set<() => void>();

function toSession(session: SupabaseSession | null): Session | null {
  if (!session || !session.access_token) return null;
  return {
    token: session.access_token,
    email: session.user?.email ?? '',
    userId: session.user?.id ?? '',
    expiresAt: typeof session.expires_at === 'number' ? session.expires_at : null,
  };
}

function readStored(): Session | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return null;
    const candidate = parsed as Partial<Session>;
    if (typeof candidate.token !== 'string' || !candidate.token) return null;
    if (typeof candidate.expiresAt === 'number' && candidate.expiresAt * 1000 <= Date.now()) {
      return null;
    }
    return {
      token: candidate.token,
      email: typeof candidate.email === 'string' ? candidate.email : '',
      userId: typeof candidate.userId === 'string' ? candidate.userId : '',
      expiresAt: typeof candidate.expiresAt === 'number' ? candidate.expiresAt : null,
    };
  } catch {
    return null;
  }
}

function persist(session: Session | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Stockage indisponible (navigation privée stricte) : session en mémoire seulement.
  }
}

function emit(): void {
  for (const listener of listeners) listener();
}

function setState(patch: Partial<AuthState>): void {
  state = { ...state, ...patch };
  if ('session' in patch) persist(state.session);
  emit();
}

function applySession(session: SupabaseSession | null): void {
  const next = toSession(session);
  if (
    state.ready &&
    next?.token === state.session?.token &&
    next?.email === state.session?.email &&
    next?.expiresAt === state.session?.expiresAt
  ) {
    return;
  }
  setState({ session: next, ready: true });
}

export function getSession(): Session | null {
  return state.session;
}

export function getToken(): string | null {
  return state.session?.token ?? null;
}

export function isAuthReady(): boolean {
  return state.ready;
}

export function isPasswordRecovery(): boolean {
  return state.recovery;
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSession(): Session | null {
  return useSyncExternalStore(subscribeSession, getSession, getSession);
}

export function useAuthReady(): boolean {
  return useSyncExternalStore(subscribeSession, isAuthReady, isAuthReady);
}

export function usePasswordRecovery(): boolean {
  return useSyncExternalStore(subscribeSession, isPasswordRecovery, isPasswordRecovery);
}

/** Déconnexion : état local vidé immédiatement, révocation Supabase en arrière-plan. */
export function clearSession(): void {
  setState({ session: null, ready: true, recovery: false });
  void Promise.resolve(supabase.auth.signOut()).catch(() => {
    /* jeton local déjà effacé ; rien d'autre à faire hors ligne */
  });
}

/** Variante attendable, pour les écrans qui confirment la déconnexion. */
export async function signOut(): Promise<void> {
  setState({ session: null, ready: true, recovery: false });
  try {
    await supabase.auth.signOut();
  } catch {
    /* idem : la session locale est déjà supprimée */
  }
}

export function completePasswordRecovery(): void {
  setState({ recovery: false });
}

if (typeof window !== 'undefined') {
  // Ancienne clé de démonstration (jeton collé) : retirée définitivement.
  try {
    localStorage.removeItem(LEGACY_DEV_TOKEN_KEY);
  } catch {
    /* ignore */
  }

  void supabase.auth.getSession().then(({ data }) => {
    applySession(data.session);
    setState({ ready: true });
  });

  // Repli : lien de réinitialisation arrivé avec `type=recovery` dans le fragment.
  try {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    if (params.get('type') === 'recovery') setState({ recovery: true });
  } catch {
    /* fragment illisible : l'événement PASSWORD_RECOVERY reste la source de vérité */
  }

  supabase.auth.onAuthStateChange((event, session) => {
    applySession(session);
    if (event === 'PASSWORD_RECOVERY') setState({ recovery: true });
  });

  // Un 401 de l'API Kwes invalide la session : on repart d'un état propre.
  window.addEventListener('kwes:unauthorized', () => {
    if (state.session) clearSession();
  });
}

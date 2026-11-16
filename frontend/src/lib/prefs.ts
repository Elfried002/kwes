import { useSyncExternalStore } from 'react';

/** Préférences locales (aucune écriture serveur : l'API n'expose pas de route profil). */

const KEY = 'kwes.prefs.v1';

export interface Preferences {
  /** Code de langue vocale (fr, en, sw, yo, ha, wo, tw, bci, dyu, bet, nouchi). */
  language: string;
  voiceEnabled: boolean;
  notificationsEnabled: boolean;
  /** Voix Gemini choisie (`null` = voix par défaut du serveur). */
  voiceId: string | null;
}

const DEFAULTS: Preferences = {
  language: 'fr',
  voiceEnabled: true,
  notificationsEnabled: false,
  voiceId: null,
};

function read(): Preferences {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return DEFAULTS;
    const candidate = parsed as Partial<Preferences>;
    return {
      language:
        typeof candidate.language === 'string' && candidate.language.trim()
          ? candidate.language.trim().slice(0, 16)
          : DEFAULTS.language,
      voiceEnabled: typeof candidate.voiceEnabled === 'boolean' ? candidate.voiceEnabled : DEFAULTS.voiceEnabled,
      notificationsEnabled:
        typeof candidate.notificationsEnabled === 'boolean'
          ? candidate.notificationsEnabled
          : DEFAULTS.notificationsEnabled,
      voiceId:
        typeof candidate.voiceId === 'string' && candidate.voiceId.trim()
          ? candidate.voiceId.trim()
          : null,
    };
  } catch {
    return DEFAULTS;
  }
}

let current = read();
const listeners = new Set<() => void>();

export function getPreferences(): Preferences {
  return current;
}

export function subscribePreferences(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function updatePreferences(patch: Partial<Preferences>): void {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    /* stockage indisponible : préférence en mémoire */
  }
  for (const listener of listeners) listener();
}

export function usePreferences(): Preferences {
  return useSyncExternalStore(subscribePreferences, getPreferences, getPreferences);
}

/** Brouillon local par conversation (conservé en mode dégradé). */
const DRAFT_PREFIX = 'kwes.draft.';

export function readDraft(key: string): string {
  try {
    return localStorage.getItem(`${DRAFT_PREFIX}${key}`) ?? '';
  } catch {
    return '';
  }
}

export function writeDraft(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(`${DRAFT_PREFIX}${key}`, value);
    else localStorage.removeItem(`${DRAFT_PREFIX}${key}`);
  } catch {
    /* ignore */
  }
}

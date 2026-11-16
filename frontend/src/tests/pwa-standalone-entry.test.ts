import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  HOME,
  STANDALONE_QUERY,
  guestScreen,
  isInstalledApp,
  parseHash,
} from '../lib/router';

/**
 * Entrée dans l'application selon le mode d'affichage.
 *
 * Installée (PWA, `display-mode: standalone` ou `navigator.standalone` sur iOS),
 * l'app ouvre sur la connexion. Sur le web ouvert, elle garde la page publique.
 */

function stubDisplay(options: {
  standalone?: boolean;
  iosStandalone?: boolean;
  matchMedia?: (query: string) => { matches: boolean };
}): void {
  vi.stubGlobal('window', {
    matchMedia:
      options.matchMedia ??
      ((query: string) => ({ matches: options.standalone === true && query === STANDALONE_QUERY })),
    navigator: { standalone: options.iosStandalone === true },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('détection du mode installé', () => {
  it('reconnaît une app installée via display-mode: standalone', () => {
    stubDisplay({ standalone: true });
    expect(isInstalledApp()).toBe(true);
  });

  it('reconnaît une app installée sur iOS via navigator.standalone', () => {
    stubDisplay({ standalone: false, iosStandalone: true });
    expect(isInstalledApp()).toBe(true);
  });

  it('laisse le web ouvert hors mode installé', () => {
    stubDisplay({ standalone: false });
    expect(isInstalledApp()).toBe(false);
  });

  it('ne casse pas si matchMedia est absent ou lève', () => {
    vi.stubGlobal('window', { navigator: {} });
    expect(isInstalledApp()).toBe(false);

    stubDisplay({
      matchMedia: () => {
        throw new Error('MediaQueryList indisponible');
      },
    });
    expect(isInstalledApp()).toBe(false);
  });
});

describe('écran d’entrée sans session', () => {
  it('app installée sur la racine : connexion, jamais la page publique', () => {
    stubDisplay({ standalone: true });
    expect(guestScreen(parseHash(''), isInstalledApp())).toBe('login');
    expect(guestScreen(HOME, isInstalledApp())).toBe('login');
  });

  it('web ouvert sur la racine : page publique intacte', () => {
    stubDisplay({ standalone: false });
    expect(guestScreen(parseHash(''), isInstalledApp())).toBe('public');
  });

  it('la connexion et la voix restent accessibles sur le web ouvert', () => {
    stubDisplay({ standalone: false });
    expect(guestScreen(parseHash('#/connexion'), isInstalledApp())).toBe('login');
    expect(guestScreen(parseHash('#/inscription'), isInstalledApp())).toBe('login');
    expect(guestScreen(parseHash('#/mot-de-passe-oublie'), isInstalledApp())).toBe('login');
    expect(guestScreen(parseHash('#/parler'), isInstalledApp())).toBe('login');
  });

  it('app installée, n’importe quelle page publique mène à la connexion', () => {
    stubDisplay({ standalone: true });
    const installed = isInstalledApp();
    expect(guestScreen({ name: 'chat' }, installed)).toBe('login');
    expect(guestScreen({ name: 'tasks' }, installed)).toBe('login');
    expect(guestScreen({ name: 'settings' }, installed)).toBe('login');
  });

  it('app installée, une adresse de connexion garde son mode', () => {
    stubDisplay({ standalone: true });
    const route = parseHash('#/inscription');
    expect(route.name).toBe('auth');
    expect(guestScreen(route, isInstalledApp())).toBe('login');
  });
});

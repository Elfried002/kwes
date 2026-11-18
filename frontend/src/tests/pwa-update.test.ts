import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  _setWaitingRegistrationForTest,
  applyUpdate,
  isUpdateAvailable,
  postponeUpdate,
} from '../lib/pwa-update';

afterEach(() => {
  _setWaitingRegistrationForTest(null);
  vi.useRealTimers();
});

describe('mise à jour PWA', () => {
  it('ne propose rien sans version en attente', () => {
    _setWaitingRegistrationForTest(null);
    expect(isUpdateAvailable()).toBe(false);
  });

  it('propose une version prête à être activée', () => {
    _setWaitingRegistrationForTest({ waiting: { postMessage: vi.fn() } });
    expect(isUpdateAvailable()).toBe(true);
  });

  it('n’active la nouvelle version qu’après l’accord explicite', () => {
    const postMessage = vi.fn();
    _setWaitingRegistrationForTest({ waiting: { postMessage } });
    expect(postMessage).not.toHaveBeenCalled();
    applyUpdate();
    expect(postMessage).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' });
    applyUpdate();
    expect(postMessage).toHaveBeenCalledTimes(1);
  });

  it('« Plus tard » masque la proposition puis la rend après 30 minutes', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-18T06:00:00Z'));
    _setWaitingRegistrationForTest({ waiting: { postMessage: vi.fn() } });

    postponeUpdate();
    expect(isUpdateAvailable()).toBe(false);

    vi.setSystemTime(new Date('2026-11-18T06:29:00Z'));
    expect(isUpdateAvailable()).toBe(false);

    vi.setSystemTime(new Date('2026-11-18T06:31:00Z'));
    expect(isUpdateAvailable()).toBe(true);
  });
});

/**
 * Mise à jour de l'application (PWA).
 *
 * Une nouvelle version reste en attente tant que l'utilisateur ne l'a pas acceptée.
 * Rien ne se recharge sans son accord : « Plus tard » masque la proposition pendant
 * 30 minutes, et le rechargement n'a lieu qu'au clic sur « Mettre à jour maintenant ».
 */

const POSTPONE_MS = 30 * 60 * 1000;
const CHECK_INTERVAL_MS = 10 * 60 * 1000;

type Listener = () => void;

interface WaitingLike {
  waiting: { postMessage: (message: unknown) => void } | null;
}

let waitingRegistration: WaitingLike | null = null;
let snoozedUntil = 0;
let applying = false;
let lastCheck = 0;
let snoozeTimer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<Listener>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

export function subscribeUpdate(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Vrai quand une version est prête et que l'utilisateur ne l'a pas reportée. */
export function isUpdateAvailable(): boolean {
  return waitingRegistration !== null && Date.now() >= snoozedUntil;
}

/** « Plus tard » : la proposition revient après 30 minutes. */
export function postponeUpdate(now: number = Date.now()): void {
  snoozedUntil = now + POSTPONE_MS;
  emit();
  if (typeof window !== 'undefined') {
    clearTimeout(snoozeTimer);
    snoozeTimer = setTimeout(emit, POSTPONE_MS);
  }
}

/** Accord explicite de l'utilisateur : la nouvelle version s'active, puis la page se recharge. */
export function applyUpdate(): void {
  const worker = waitingRegistration?.waiting;
  if (!worker || applying) return;
  applying = true;
  worker.postMessage({ type: 'SKIP_WAITING' });
}

function track(registration: ServiceWorkerRegistration): void {
  // Pas de proposition lors de la toute première installation (aucune page contrôlée).
  if (registration.waiting && navigator.serviceWorker.controller) {
    waitingRegistration = registration;
    emit();
  }
}

/** Enregistre le service worker et surveille les nouvelles versions. */
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) return;

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (applying) window.location.reload();
  });

  navigator.serviceWorker
    .register('/sw.js')
    .then((registration) => {
      track(registration);

      registration.addEventListener('updatefound', () => {
        const worker = registration.installing;
        worker?.addEventListener('statechange', () => {
          if (worker.state === 'installed') track(registration);
        });
      });

      // Vérification au retour sur l'onglet, au plus toutes les 10 minutes.
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return;
        const now = Date.now();
        if (now - lastCheck < CHECK_INTERVAL_MS) return;
        lastCheck = now;
        void registration.update().catch(() => {});
      });
    })
    .catch((cause: unknown) => {
      console.warn('[Kwes] Enregistrement du service worker impossible', cause);
    });
}

/** Réservé aux tests : remet l'état à zéro et fixe une version en attente. */
export function _setWaitingRegistrationForTest(registration: WaitingLike | null): void {
  waitingRegistration = registration;
  snoozedUntil = 0;
  applying = false;
  emit();
}

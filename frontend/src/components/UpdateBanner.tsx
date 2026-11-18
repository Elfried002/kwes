import { useSyncExternalStore } from 'react';
import { applyUpdate, isUpdateAvailable, postponeUpdate, subscribeUpdate } from '../lib/pwa-update';

/** Proposition de mise à jour : discrète, jamais bloquante, rien ne se recharge sans clic. */
export function UpdateBanner() {
  const available = useSyncExternalStore(subscribeUpdate, isUpdateAvailable, () => false);
  if (!available) return null;

  return (
    <div className="pwa-update" role="status" aria-live="polite">
      <div className="pwa-update__text">
        <strong>Une nouvelle version de Kwes est prête.</strong>
        <span>Le rechargement interrompt ce qui est en cours à l’écran.</span>
      </div>
      <div className="pwa-update__actions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => postponeUpdate()}>
          Plus tard
        </button>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => applyUpdate()}>
          Mettre à jour maintenant
        </button>
      </div>
    </div>
  );
}

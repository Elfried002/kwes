import { useEffect, useState } from 'react';

/**
 * Ouverture de l'application : le droïde s'allume, puis s'efface.
 *
 * Affiché une fois par session (sessionStorage), jamais pendant une navigation
 * interne. Respecte `prefers-reduced-motion` : dans ce cas, simple fondu court.
 */
export function BootSplash() {
  const [visible, setVisible] = useState(() => {
    try {
      return sessionStorage.getItem('kwes.booted') !== '1';
    } catch {
      return false;
    }
  });
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (!visible) return;
    try {
      sessionStorage.setItem('kwes.booted', '1');
    } catch {
      /* stockage indisponible : l'animation se joue quand même */
    }
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
    const hold = reduced ? 380 : 1150;
    const fadeOut = window.setTimeout(() => setLeaving(true), hold);
    const done = window.setTimeout(() => setVisible(false), hold + 420);
    return () => {
      window.clearTimeout(fadeOut);
      window.clearTimeout(done);
    };
  }, [visible]);

  if (!visible) return null;

  return (
    <div className="boot" data-leaving={leaving ? 'true' : 'false'} aria-hidden="true">
      <div className="boot__glow" />
      <img className="boot__head" src="/brand/droid-head.svg" alt="" width={96} height={96} />
      <p className="boot__name">KWES</p>
    </div>
  );
}
